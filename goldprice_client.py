from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

import httpx


BASE_URL = "https://api.goldprice.dev/v1"
SPOT_SYMBOL = "XAU-USD-SPOT"

# M3 and M10 are locally resampled from real 1m data because they are not
# native documented goldprice.dev API intervals.
API_INTERVALS = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
}

RESAMPLED_INTERVALS = {
    "M3": ("1m", 3),
    "M10": ("1m", 10),
}

SUPPORTED_TIMEFRAMES = frozenset(API_INTERVALS) | frozenset(RESAMPLED_INTERVALS)

MAX_PAGES = 100
MAX_COLLECTED_BARS = 100_000


class FeedStatus(str, Enum):
    OK = "OK"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    PLAN_GATED = "PLAN_GATED"
    RATE_LIMITED = "RATE_LIMITED"
    NO_DATA = "NO_DATA"
    INVALID_DATA = "INVALID_DATA"
    INVALID_REQUEST = "INVALID_REQUEST"
    STALE_DATA = "STALE_DATA"


T = TypeVar("T")


@dataclass(frozen=True)
class FeedResult(Generic[T]):
    status: FeedStatus
    data: T | None = None
    reason: str | None = None
    http_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == FeedStatus.OK


@dataclass(frozen=True)
class SpotQuote:
    symbol: str
    quote_currency: str
    price: Decimal
    bid: Decimal | None
    ask: Decimal | None
    spread: Decimal | None
    computed_at: datetime
    is_stale: bool


@dataclass(frozen=True)
class OHLCVBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    is_closed: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | date, *, name: str) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)

    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime or date")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")

    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO-8601 timestamp")

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        timestamp = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not a valid ISO-8601 timestamp") from exc

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")

    return timestamp.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal(
    value: Any,
    *,
    name: str,
    allow_none: bool = False,
) -> Decimal | None:
    if value is None and allow_none:
        return None

    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite numeric value")

    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite numeric value") from exc

    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")

    if not math.isfinite(float(parsed)):
        raise ValueError(f"{name} must be finite")

    return parsed


def _safe_error_body(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:500] or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        values = [
            payload.get("error"),
            payload.get("detail"),
            payload.get("message"),
        ]
        message = ": ".join(str(value) for value in values if value is not None)
        if message:
            return message[:500]

    return f"HTTP {response.status_code}"


def _http_status(response: httpx.Response) -> FeedStatus:
    if response.status_code == 403:
        return FeedStatus.PLAN_GATED
    if response.status_code == 429:
        return FeedStatus.RATE_LIMITED
    if response.status_code in (400, 422):
        return FeedStatus.INVALID_REQUEST
    if 500 <= response.status_code <= 599:
        return FeedStatus.DATA_SOURCE_UNAVAILABLE
    if response.status_code == 200:
        return FeedStatus.OK
    return FeedStatus.DATA_SOURCE_UNAVAILABLE


def _validate_bar(raw: Any, *, now: datetime) -> OHLCVBar:
    if not isinstance(raw, dict):
        raise ValueError("bar must be an object")

    timestamp = _parse_timestamp(raw.get("bar_start"), name="bar_start")

    if timestamp > now:
        raise ValueError("future bar is not allowed")

    is_closed = raw.get("is_closed")
    if not isinstance(is_closed, bool):
        raise ValueError("is_closed must be boolean")

    open_ = _decimal(raw.get("open"), name="open")
    high = _decimal(raw.get("high"), name="high")
    low = _decimal(raw.get("low"), name="low")
    close = _decimal(raw.get("close"), name="close")
    volume = _decimal(raw.get("volume"), name="volume", allow_none=True)

    assert open_ is not None
    assert high is not None
    assert low is not None
    assert close is not None

    if any(value <= 0 for value in (open_, high, low, close)):
        raise ValueError("OHLC values must be positive")

    if volume is not None and volume < 0:
        raise ValueError("volume cannot be negative")

    if high < max(open_, close, low):
        raise ValueError("high must be >= max(open, close, low)")

    if low > min(open_, close, high):
        raise ValueError("low must be <= min(open, close, high)")

    return OHLCVBar(
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        is_closed=is_closed,
    )


def _sort_and_reject_duplicates(
    bars: list[OHLCVBar],
) -> list[OHLCVBar]:
    ordered = sorted(bars, key=lambda item: item.timestamp)
    seen: set[datetime] = set()

    for item in ordered:
        if item.timestamp in seen:
            raise ValueError(
                f"duplicate timestamp: {_iso_utc(item.timestamp)}"
            )
        seen.add(item.timestamp)

    return ordered


def _bucket_start(timestamp: datetime, minutes: int) -> datetime:
    timestamp = timestamp.astimezone(timezone.utc)
    minute = timestamp.minute - (timestamp.minute % minutes)
    return timestamp.replace(
        minute=minute,
        second=0,
        microsecond=0,
    )


def _resample_complete(
    source_bars: list[OHLCVBar],
    *,
    minutes: int,
    start: datetime,
    end: datetime,
    now: datetime,
) -> list[OHLCVBar]:
    source_bars = _sort_and_reject_duplicates(source_bars)
    groups: dict[datetime, list[OHLCVBar]] = {}

    for source in source_bars:
        if not source.is_closed:
            continue
        if source.timestamp < start or source.timestamp > end:
            continue
        if source.timestamp > now:
            continue

        groups.setdefault(
            _bucket_start(source.timestamp, minutes),
            [],
        ).append(source)

    expected_delta = timedelta(minutes=1)
    result: list[OHLCVBar] = []

    for bucket_start, group in groups.items():
        bucket_end = bucket_start + timedelta(minutes=minutes)

        if bucket_start < start or bucket_end > end:
            continue

        if bucket_end > now:
            continue

        group = sorted(group, key=lambda item: item.timestamp)

        if len(group) != minutes:
            continue

        expected_timestamps = [
            bucket_start + (expected_delta * offset)
            for offset in range(minutes)
        ]

        if [item.timestamp for item in group] != expected_timestamps:
            continue

        volumes = [item.volume for item in group]
        total_volume = (
            sum(volume for volume in volumes if volume is not None)
            if all(volume is not None for volume in volumes)
            else None
        )

        result.append(
            OHLCVBar(
                timestamp=bucket_start,
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=total_volume,
                is_closed=True,
            )
        )

    return _sort_and_reject_duplicates(result)


class GoldPriceClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float = 10.0,
        base_url: str = BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._client = http_client
        self._owns_client = http_client is None
        self._clock = clock

    async def __aenter__(self) -> "GoldPriceClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        if self._owns_client:
            self._client = None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> FeedResult[dict[str, Any]]:
        if self._client is None:
            return FeedResult(
                FeedStatus.DATA_SOURCE_UNAVAILABLE,
                reason="client is not open",
            )

        try:
            response = await self._client.get(
                f"{self._base_url}{path}",
                params=params,
                headers=self._headers(),
            )
        except httpx.TimeoutException:
            return FeedResult(
                FeedStatus.DATA_SOURCE_UNAVAILABLE,
                reason="goldprice.dev request timed out",
            )
        except httpx.RequestError as exc:
            return FeedResult(
                FeedStatus.DATA_SOURCE_UNAVAILABLE,
                reason=f"goldprice.dev network error: {type(exc).__name__}",
            )

        status = _http_status(response)

        if response.status_code != 200:
            return FeedResult(
                status,
                reason=_safe_error_body(response),
                http_status=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="successful response was not valid JSON",
                http_status=response.status_code,
            )

        if not isinstance(payload, dict):
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="successful response must be a JSON object",
                http_status=response.status_code,
            )

        return FeedResult(
            FeedStatus.OK,
            data=payload,
            http_status=response.status_code,
        )

    async def get_spot(self) -> FeedResult[SpotQuote]:
        result = await self._get(
            "/prices",
            params={"symbol": SPOT_SYMBOL},
        )

        if not result.ok:
            return FeedResult(
                result.status,
                reason=result.reason,
                http_status=result.http_status,
            )

        assert result.data is not None
        symbols = result.data.get("symbols")

        if not isinstance(symbols, list) or not symbols:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="successful response does not contain symbols[]",
            )

        row = next(
            (
                item
                for item in symbols
                if isinstance(item, dict)
                and item.get("symbol") == "XAU"
                and item.get("quote_currency") == "USD"
            ),
            None,
        )

        if row is None:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="XAU/USD spot row is missing",
            )

        try:
            price = _decimal(row.get("price"), name="price")
            bid = _decimal(row.get("bid"), name="bid", allow_none=True)
            ask = _decimal(row.get("ask"), name="ask", allow_none=True)
            computed_at = _parse_timestamp(
                row.get("computed_at"),
                name="computed_at",
            )
        except ValueError as exc:
            return FeedResult(FeedStatus.INVALID_DATA, reason=str(exc))

        is_stale = row.get("is_stale")

        if price is None or price <= 0:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="spot price is missing or non-positive",
            )

        if bid is not None and bid <= 0:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="bid is non-positive",
            )

        if ask is not None and ask <= 0:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="ask is non-positive",
            )

        if bid is not None and ask is not None and ask < bid:
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="ask cannot be lower than bid",
            )

        if not isinstance(is_stale, bool):
            return FeedResult(
                FeedStatus.INVALID_DATA,
                reason="is_stale must be boolean",
            )

        quote = SpotQuote(
            symbol=SPOT_SYMBOL,
            quote_currency="USD",
            price=price,
            bid=bid,
            ask=ask,
            spread=ask - bid if bid is not None and ask is not None else None,
            computed_at=computed_at,
            is_stale=is_stale,
        )

        if is_stale:
            return FeedResult(
                FeedStatus.STALE_DATA,
                data=quote,
                reason="goldprice.dev marked the quote as stale",
            )

        return FeedResult(FeedStatus.OK, data=quote)

    async def _fetch_bars(
        self,
        *,
        api_interval: str,
        start: datetime,
        end: datetime,
        count: int,
        custom_minutes: int | None = None,
    ) -> FeedResult[list[OHLCVBar]]:
        now = self._clock().astimezone(timezone.utc)
        collected: list[OHLCVBar] = []
        seen_timestamps: set[datetime] = set()
        cursor: str | None = None
        seen_cursors: set[str] = set()

        requested_source_bars = (
            count * custom_minutes
            if custom_minutes is not None
            else count
        )
        page_limit = max(1, min(10_000, requested_source_bars))

        for _ in range(MAX_PAGES):
            if len(collected) >= MAX_COLLECTED_BARS:
                return FeedResult(
                    FeedStatus.INVALID_DATA,
                    reason="bar collection safety limit exceeded",
                )

            params: dict[str, Any] = {
                "symbol": SPOT_SYMBOL,
                "interval": api_interval,
                "from": _iso_utc(start),
                "to": _iso_utc(end),
                "limit": page_limit,
            }

            if cursor is not None:
                params["cursor"] = cursor

            page_result = await self._get("/bars", params=params)

            if not page_result.ok:
                return FeedResult(
                    page_result.status,
                    reason=page_result.reason,
                    http_status=page_result.http_status,
                )

            assert page_result.data is not None
            raw_bars = page_result.data.get("bars")

            if not isinstance(raw_bars, list):
                return FeedResult(
                    FeedStatus.INVALID_DATA,
                    reason="successful response does not contain bars[]",
                )

            if not raw_bars:
                if not collected:
                    return FeedResult(
                        FeedStatus.NO_DATA,
                        reason="goldprice.dev returned an empty bars[]",
                    )
                break

            page_bars: list[OHLCVBar] = []

            try:
                for raw_bar in raw_bars:
                    parsed = _validate_bar(raw_bar, now=now)

                    if parsed.timestamp in seen_timestamps:
                        raise ValueError(
                            "duplicate timestamp across API pages: "
                            f"{_iso_utc(parsed.timestamp)}"
                        )

                    seen_timestamps.add(parsed.timestamp)
                    page_bars.append(parsed)
            except ValueError as exc:
                return FeedResult(FeedStatus.INVALID_DATA, reason=str(exc))

            for parsed in page_bars:
                if parsed.timestamp < start or parsed.timestamp > end:
                    continue
                if parsed.timestamp > now:
                    continue
                if not parsed.is_closed:
                    continue
                collected.append(parsed)

            ordered_source = _sort_and_reject_duplicates(collected)

            if custom_minutes is None:
                if len(ordered_source) >= count:
                    return FeedResult(
                        FeedStatus.OK,
                        data=ordered_source[-count:],
                    )
            else:
                try:
                    formed = _resample_complete(
                        ordered_source,
                        minutes=custom_minutes,
                        start=start,
                        end=end,
                        now=now,
                    )
                except ValueError as exc:
                    return FeedResult(
                        FeedStatus.INVALID_DATA,
                        reason=str(exc),
                    )

                if len(formed) >= count:
                    return FeedResult(
                        FeedStatus.OK,
                        data=formed[-count:],
                    )

            next_cursor = page_result.data.get("next_cursor")

            if next_cursor is None:
                break

            if not isinstance(next_cursor, str) or not next_cursor:
                return FeedResult(
                    FeedStatus.INVALID_DATA,
                    reason="next_cursor must be a non-empty string or null",
                )

            if next_cursor in seen_cursors:
                return FeedResult(
                    FeedStatus.INVALID_DATA,
                    reason="next_cursor loop detected",
                )

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        ordered_source = _sort_and_reject_duplicates(collected)

        if custom_minutes is None:
            final_bars = ordered_source[-count:]
        else:
            try:
                final_bars = _resample_complete(
                    ordered_source,
                    minutes=custom_minutes,
                    start=start,
                    end=end,
                    now=now,
                )[-count:]
            except ValueError as exc:
                return FeedResult(
                    FeedStatus.INVALID_DATA,
                    reason=str(exc),
                )

        if not final_bars:
            return FeedResult(
                FeedStatus.NO_DATA,
                reason="no valid closed bars were available",
            )

        return FeedResult(FeedStatus.OK, data=final_bars)

    async def get_bars(
        self,
        timeframe: str,
        *,
        start: datetime | date,
        end: datetime | date,
        count: int,
    ) -> FeedResult[list[OHLCVBar]]:
        timeframe = timeframe.upper()

        if timeframe not in SUPPORTED_TIMEFRAMES:
            return FeedResult(
                FeedStatus.INVALID_REQUEST,
                reason=f"unsupported timeframe: {timeframe}",
            )

        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            return FeedResult(
                FeedStatus.INVALID_REQUEST,
                reason="count must be a positive integer",
            )

        try:
            start_utc = _as_utc(start, name="start")
            end_utc = _as_utc(end, name="end")
        except ValueError as exc:
            return FeedResult(FeedStatus.INVALID_REQUEST, reason=str(exc))

        if start_utc > end_utc:
            return FeedResult(
                FeedStatus.INVALID_REQUEST,
                reason="start must not be later than end",
            )

        if timeframe in API_INTERVALS:
            return await self._fetch_bars(
                api_interval=API_INTERVALS[timeframe],
                start=start_utc,
                end=end_utc,
                count=count,
            )

        api_interval, minutes = RESAMPLED_INTERVALS[timeframe]

        return await self._fetch_bars(
            api_interval=api_interval,
            start=start_utc,
            end=end_utc,
            count=count,
            custom_minutes=minutes,
        )
