from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import Group, User


def today_uz() -> date:
    """Oʻzbekiston vaqti (UTC+5) boʻyicha bugungi sana."""
    return (datetime.now(timezone.utc) + timedelta(hours=5)).date()


def month_of(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def month_bounds(m: str):
    y, mo = int(m[:4]), int(m[5:7])
    first = date(y, mo, 1)
    nxt = date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1)
    return first, nxt


def next_month(m: str) -> str:
    return month_of(month_bounds(m)[1])


def effective_fee(u: User, groups: dict) -> int:
    """Yagona joy — oʻquvchining oylik toʻlovi. Kelajakda multi-enrollment boʻlsa, faqat shu funksiya oʻzgaradi."""
    if u.monthly_fee and u.monthly_fee > 0:
        return u.monthly_fee
    g: Optional[Group] = groups.get(u.group_id)
    return g.monthly_fee if g and g.monthly_fee else 0


def clamp_day(m: str, day: int) -> date:
    first, nxt = month_bounds(m)
    last = (nxt - timedelta(days=1)).day
    return date(first.year, first.month, max(1, min(day, last)))


def pay_status(fee: int, paid: int, month: str, fee_day: int, today: date, grace_days: int = 0) -> str:
    """Status matni: nofee|paid|partial|partial_late|unpaid|overdue. `grace_days` TZ-7."""
    if fee <= 0:
        return "nofee"
    if paid >= fee:
        return "paid"
    due = clamp_day(month, fee_day) + timedelta(days=max(0, grace_days))
    late = today > due
    if paid > 0:
        return "partial_late" if late else "partial"
    return "overdue" if late else "unpaid"


def round_to(n: float, step: int) -> int:
    """`n`ni `step`ga karrali qilib yaxlitlash (TZ-7 prorate uchun)."""
    if step <= 0:
        return int(round(n))
    return int(round(n / step) * step)


def first_month_amount(fee: int, month: str, started_on: Optional[date], mode: str, round_step: int) -> int:
    """TZ-7 A: birinchi oy narxi. `mode`: full|prorate|free."""
    if mode == "full" or fee <= 0:
        return fee
    first, nxt = month_bounds(month)
    if not started_on or started_on <= first:
        return fee
    if started_on >= nxt:
        return 0
    if mode == "free":
        return 0
    # mode == "prorate"
    days_in_month = (nxt - first).days
    remaining = (nxt - started_on).days  # boshlanish kunini ham qo'shadi
    if days_in_month <= 0:
        return 0
    raw = fee * remaining / days_in_month
    return round_to(raw, round_step)
