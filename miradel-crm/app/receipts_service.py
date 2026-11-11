from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Payment


def generate_receipt_no(db: Session, paid_on: date) -> str:
    year = paid_on.year
    prefix = f"R-{year}-"
    # Find the highest receipt_no for this year
    last = db.scalar(
        select(Payment.receipt_no)
        .where(Payment.receipt_no.like(f"{prefix}%"))
        .order_by(Payment.receipt_no.desc())
        .limit(1)
    )
    seq = 1
    if last and len(last) > len(prefix):
        try:
            seq = int(last[len(prefix):]) + 1
        except ValueError:
            pass
    return f"{prefix}{seq:05d}"


def backfill_receipts(db: Session):
    """Idempotent backfill for payments that do not have a receipt number."""
    missing = list(db.scalars(select(Payment).where(Payment.receipt_no.is_(None), Payment.voided.is_(False)).order_by(Payment.id)))
    for p in missing:
        p.receipt_no = generate_receipt_no(db, p.paid_on)
    if missing:
        db.commit()
