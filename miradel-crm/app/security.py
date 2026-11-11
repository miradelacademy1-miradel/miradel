import secrets
import string
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher

from .config import PASSWORD_LENGTH, SECRET_KEY, TOKEN_HOURS

_ph = PasswordHasher()


def hash_password(p: str) -> str:
    return _ph.hash(p)


def verify_password(h: str, p: str) -> bool:
    try:
        return _ph.verify(h, p)
    except Exception:
        return False


def gen_password(n: int = PASSWORD_LENGTH) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(n))


def make_token(uid: int, tv: int = 0) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": str(uid), "tv": tv, "exp": exp}, SECRET_KEY, algorithm="HS256")


def read_token(t: str) -> Optional[tuple]:
    """(foydalanuvchi id, token versiyasi) yoki None."""
    try:
        d = jwt.decode(t, SECRET_KEY, algorithms=["HS256"])
        return int(d["sub"]), int(d.get("tv", 0))
    except Exception:
        return None


# Oddiy urinishlarni cheklash (bitta server nusxasi uchun; keyinroq Redis/DB ga koʻchiriladi)
_FAILS: dict = {}
MAX_FAILS, LOCK_SEC, WINDOW = 5, 300, 600


def locked(key: str) -> int:
    rec = _FAILS.get(key)
    if rec and rec["until"] > time.time():
        return int(rec["until"] - time.time())
    return 0


def fail(key: str) -> None:
    t = time.time()
    rec = _FAILS.get(key)
    if not rec or t - rec["first"] > WINDOW:
        rec = {"n": 0, "first": t, "until": 0}
    rec["n"] += 1
    if rec["n"] >= MAX_FAILS:
        rec["until"] = t + LOCK_SEC
        rec["n"] = 0
        rec["first"] = t
    _FAILS[key] = rec


def clear(key: str) -> None:
    _FAILS.pop(key, None)
