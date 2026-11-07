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
    return first, nxt  # [first, nxt)


def next_month(m: str) -> str:
    return month_of(month_bounds(m)[1])


def effective_fee(u: User, groups: dict) -> int:
    if u.monthly_fee and u.monthly_fee > 0:
        return u.monthly_fee
    g: Optional[Group] = groups.get(u.group_id)
    return g.monthly_fee if g and g.monthly_fee else 0


def clamp_day(m: str, day: int) -> date:
    first, nxt = month_bounds(m)
    last = (nxt - timedelta(days=1)).day
    return date(first.year, first.month, max(1, min(day, last)))


def pay_status(fee: int, paid: int, month: str, fee_day: int, today: date) -> str:
    if fee <= 0:
        return "nofee"
    if paid >= fee:
        return "paid"
    due = clamp_day(month, fee_day)
    late = today > due
    if paid > 0:
        return "partial_late" if late else "partial"
    return "overdue" if late else "unpaid"
