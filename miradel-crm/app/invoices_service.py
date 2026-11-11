"""TZ-4 A + TZ-7 B/D: invoice generation, discounts, freezes, due-day convergence."""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .finance import effective_fee, first_month_amount, month_bounds, month_of, round_to
from .models import (
    BillingFreeze, DiscountPreset, Group, Invoice, StudentDiscount, User,
)
from .pay_settings import load_pay_settings


def is_frozen(db: Session, student_id: int, month: str) -> bool:
    return db.scalar(select(BillingFreeze.id).where(
        BillingFreeze.student_id == student_id,
        BillingFreeze.from_month <= month,
        BillingFreeze.to_month >= month,
        BillingFreeze.voided.is_(False),
    )) is not None


def compute_discounts(db: Session, student_id: int, month: str, amount_due: int) -> tuple[int, str]:
    """Faol chegirmalarni yigʻib qaytaradi: (discount, reason)."""
    discounts = list(db.scalars(select(StudentDiscount).where(
        StudentDiscount.student_id == student_id,
        StudentDiscount.voided.is_(False),
        StudentDiscount.from_month <= month,
        or_(StudentDiscount.to_month.is_(None), StudentDiscount.to_month >= month),
    )))
    total = 0
    names = []
    for d in discounts:
        if d.kind == "percent":
            total += round(amount_due * d.value / 100)
        elif d.kind == "amount":
            total += d.value
        if d.preset_id:
            p = db.get(DiscountPreset, d.preset_id)
            if p:
                names.append(p.name)
        elif d.reason:
            names.append(d.reason)
    total = min(total, amount_due)
    return total, ", ".join(names)[:200]


def compute_due_day(db: Session, s: User, month: str, cfg: dict) -> Optional[int]:
    """TZ-7 D: due-day convergence. `users.fee_day_origin` va `users.fee_day` ni yangilaydi."""
    if not cfg["converge_enabled"]:
        return None
    target = cfg["converge_target_day"]
    months = cfg["converge_months"]

    # Oldingi oy invoice.due_day yoki users.fee_day
    first, _ = month_bounds(month)
    prev_month = month_of(first - timedelta(days=1))
    prev = db.scalar(select(Invoice).where(
        Invoice.student_id == s.id, Invoice.month == prev_month
    ))

    d_prev = prev.due_day if prev and prev.due_day else s.fee_day

    if s.fee_day_origin is None:
        s.fee_day_origin = d_prev

    origin = s.fee_day_origin

    if d_prev <= target:
        d_new = d_prev
    else:
        if origin <= target:
            step = 0
        else:
            step = -(-(origin - target) // months)  # ceil division
        d_new = max(target, d_prev - step)

    s.fee_day = d_new
    return d_new


def generate_month(db: Session, month: str) -> dict:
    """Idempotent: mavjud invoice'lar qayta yaratilmaydi."""
    cfg = load_pay_settings(db)
    bsm = cfg["billing_start_month"]
    if bsm and month < bsm:
        return {"month": month, "created": 0, "skipped": 0, "reason": "before_billing_start"}

    first, nxt = month_bounds(month)
    groups = {g.id: g for g in db.scalars(select(Group))}

    created = 0
    skipped = 0
    frozen = 0
    no_fee = 0

    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True))):
        existing = db.scalar(select(Invoice.id).where(
            Invoice.student_id == s.id, Invoice.month == month
        ))
        if existing:
            skipped += 1
            continue

        if is_frozen(db, s.id, month):
            frozen += 1
            continue

        started = s.started_on
        if started and started >= nxt:
            continue

        fee = effective_fee(s, groups)
        if fee <= 0:
            no_fee += 1
            continue

        if started and first <= started < nxt:
            amount_due = first_month_amount(fee, month, started, cfg["first_month_mode"], cfg["prorate_round"])
        else:
            amount_due = fee

        discount, reason = compute_discounts(db, s.id, month, amount_due)
        due_day = compute_due_day(db, s, month, cfg)

        db.add(Invoice(
            student_id=s.id, month=month,
            amount_due=amount_due,
            discount=discount, discount_reason=reason,
            due_day=due_day,
        ))
        created += 1

    db.commit()
    return {"month": month, "created": created, "skipped": skipped, "frozen": frozen, "no_fee": no_fee}


def recalc_invoice_discounts(db: Session, student_id: int, month: str) -> None:
    """TZ-7 B: chegirma qoʻshilganda/void qilinganda mavjud invoice'ni yangilash.
    Faqat `manual=False` va `waived=False` invoice'lar yangilanadi."""
    inv = db.scalar(select(Invoice).where(Invoice.student_id == student_id, Invoice.month == month))
    if not inv or inv.manual or inv.waived:
        return
    discount, reason = compute_discounts(db, student_id, month, inv.amount_due)
    inv.discount = discount
    inv.discount_reason = reason
