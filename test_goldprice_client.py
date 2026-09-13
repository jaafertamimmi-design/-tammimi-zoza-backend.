from datetime import datetime, timezone

import httpx
import pytest

from app.goldprice_client import FeedStatus, GoldPriceClient


UTC = timezone.utc
START = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
END = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def make_bar(minute, *, hour=10, closed=True, high="2510", low="2490"):
    return {
        "bar_start": f"2026-09-11T{hour:02d}:{minute:02d}:00Z",
        "open": "2500", "high": high, "low": low, "close": "2505",
        "volume": None, "is_closed": closed,
    }


def make_payload(bars, cursor=None):
    return {"symbol": "XAU-USD-SPOT", "interval": "1m", "bars": bars, "next_cursor": cursor}


def make_client(responses):
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        assert queue, "unexpected request"
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        status, payload = response
        return httpx.Response(status, json=payload, request=request)

    return GoldPriceClient(
        "test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.goldprice.dev/v1"),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_newest_first_response_is_returned_chronologically():
    client = make_client([(200, make_payload([make_bar(2), make_bar(1), make_bar(0)]))])
    result = await client.get_bars("M1", start=START, end=END, count=3)
    assert result.status is FeedStatus.OK
    assert [bar.timestamp.minute for bar in result.data] == [0, 1, 2]
    await client.aclose()


@pytest.mark.asyncio
async def test_forming_candles_are_excluded():
    client = make_client([(200, make_payload([make_bar(3, closed=False), make_bar(2), make_bar(1)]))])
    result = await client.get_bars("M1", start=START, end=END, count=3)
    assert result.status is FeedStatus.OK
    assert [bar.timestamp.minute for bar in result.data] == [1, 2]
    await client.aclose()


@pytest.mark.asyncio
async def test_duplicate_timestamps_across_pages_are_invalid():
    duplicate = make_bar(5)
    client = make_client([(200, make_payload([duplicate], cursor="page-2")), (200, make_payload([duplicate]))])
    result = await client.get_bars("M1", start=START, end=END, count=2)
    assert result.status is FeedStatus.INVALID_DATA
    assert "duplicate" in result.reason
    await client.aclose()


@pytest.mark.asyncio
async def test_m3_requires_more_source_bars_than_first_page():
    client = make_client([
        (200, make_payload([make_bar(2), make_bar(1)], cursor="page-2")),
        (200, make_payload([make_bar(0)])),
    ])
    result = await client.get_bars("M3", start=START, end=END, count=1)
    assert result.status is FeedStatus.OK
    assert len(result.data) == 1
    assert result.data[0].timestamp.minute == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_http_500_is_data_source_unavailable():
    client = make_client([(500, {"error": "internal_error", "detail": "temporary failure"})])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.DATA_SOURCE_UNAVAILABLE
    assert result.http_status == 500
    await client.aclose()


@pytest.mark.asyncio
async def test_network_timeout_is_data_source_unavailable():
    client = make_client([httpx.ReadTimeout("timed out")])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.DATA_SOURCE_UNAVAILABLE
    assert "timed out" in result.reason
    await client.aclose()


@pytest.mark.asyncio
async def test_successful_empty_bars_is_no_data():
    client = make_client([(200, make_payload([]))])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.NO_DATA
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_ohlc_is_invalid_data():
    client = make_client([(200, make_payload([make_bar(1, high="2480")]))])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.INVALID_DATA
    await client.aclose()


@pytest.mark.asyncio
async def test_future_bar_is_invalid_data():
    client = make_client([(200, make_payload([{**make_bar(1), "bar_start": "2026-09-11T12:01:00Z"}]))])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.INVALID_DATA
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_timeframe_is_invalid_request():
    client = make_client([])
    result = await client.get_bars("M2", start=START, end=END, count=1)
    assert result.status is FeedStatus.INVALID_REQUEST
    await client.aclose()


@pytest.mark.asyncio
async def test_403_is_plan_gated():
    client = make_client([(403, {"error": "plan_gated"})])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.PLAN_GATED
    await client.aclose()


@pytest.mark.asyncio
async def test_429_is_rate_limited():
    client = make_client([(429, {"error": "rate_limited"})])
    result = await client.get_bars("M1", start=START, end=END, count=1)
    assert result.status is FeedStatus.RATE_LIMITED
    await client.aclose()
