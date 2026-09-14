"""
محرك الأمان: تشفير كلمات المرور، JWT، وحماية من محاولات الدخول المتكررة (Brute-force)
"""
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict

from passlib.context import CryptContext
from jose import JWTError, jwt

# ==========================================
# إعدادات أساسية (تُقرأ من ملف .env - لا تُكتب المفاتيح هنا مباشرة أبداً)
# ==========================================
SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET غير موجود بملف .env! ولّد مفتاح قوي عبر: "
        "python -c \"import secrets; print(secrets.token_hex(32))\""
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # 12 ساعة بدل 24 (تقليل نافذة الخطر لو انسرق التوكن)

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
if not ADMIN_EMAIL:
    raise RuntimeError("ADMIN_EMAIL غير محدد بملف .env")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SecurityEngine:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire, "iat": datetime.utcnow()})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        try:
            return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except JWTError:
            return None


# ==========================================
# حماية Brute-force بسيطة (in-memory rate limiter)
# لحماية أقوى بالإنتاج يفضل استخدام Redis، لكن هذا كافٍ لبداية آمنة
# ==========================================
class RateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: Dict[str, list] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        hits = self._hits.get(key, [])
        hits = [t for t in hits if now - t < self.window_seconds]
        if len(hits) >= self.max_attempts:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True

    def seconds_until_allowed(self, key: str) -> int:
        hits = self._hits.get(key, [])
        if not hits:
            return 0
        oldest = min(hits)
        remaining = int(self.window_seconds - (time.time() - oldest))
        return max(0, remaining)


login_rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)
register_rate_limiter = RateLimiter(max_attempts=3, window_seconds=300)
