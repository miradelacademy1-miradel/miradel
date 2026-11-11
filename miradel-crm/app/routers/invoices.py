"""TZ-4 A: minimal invoice endpoints. TZ-7 uchun zarur."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..finance import month_bounds, month_of, today_uz
from ..invoices_service import generate_month
from ..models import Group, Invoice, User
from .admin import audit
from .manager import finance_user

router = APIRouter(prefix="/api/manager", tags=["invoices"], dependencies=[Depends(finance_user)])
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


def _inv_out(inv: Invoice, s: Optional[User] = None, g: Optional[Group] = None) -> dict:
    return {
        "id": inv.id,
        "student_id": inv.student_id,
        "student_name": s.full_name if s else "",
        "group_name": g.name if g else "",
        "month": inv.month,
        "amount_due": inv.amount_due,
        "discount": inv.discount,
        "discount_reason": inv.discount_reason,
        "waived": inv.waived,
        "note": inv.note,
        "manual": inv.manual,
        "due_day": inv.due_day,
        "net": 0 if inv.waived else max(0, inv.amount_due - inv.discount),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


@router.get("/invoices")
def list_invoices(
    month: Optional[str] = Query(None, pattern=MONTH),
    student_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Invoice).order_by(Invoice.month.desc(), Invoice.id.desc()).limit(1000)
    if month:
        stmt = stmt.where(Invoice.month == month)
    if student_id:
        stmt = stmt.where(Invoice.student_id == student_id)
    invs = list(db.scalars(stmt))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({i.student_id for i in invs})))}
    groups = {g.id: g for g in db.scalars(select(Group))}
    return [_inv_out(inv, users.get(inv.student_id), groups.get(users.get(inv.student_id).group_id) if users.get(inv.student_id) else None) for inv in invs]


class InvPatch(BaseModel):
    discount: Optional[int] = Field(default=None, ge=0)
    discount_reason: Optional[str] = Field(default=None, max_length=200)
    waived: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=200)


@router.patch("/invoices/{iid}")
def patch_invoice(
    iid: int,
    body: InvPatch,
    me: User = Depends(finance_user),
    db: Session = Depends(get_db),
):
    inv = db.get(Invoice, iid)
    if not inv:
        raise HTTPException(404, "Invoice topilmadi")
    data = body.model_dump(exclude_unset=True)
    new_discount = data.get("discount", inv.discount)
    new_waived = data.get("waived", inv.waived)
    new_reason = data.get("discount_reason", inv.discount_reason) or ""

    if new_discount < 0 or new_discount > inv.amount_due:
        raise HTTPException(400, "Chegirma 0..amount_due orasida boʻlsin")
    if (new_discount > 0 or new_waived) and len(new_reason.strip()) < 3:
        raise HTTPException(400, "Sabab kamida 3 belgi boʻlishi kerak")

    if "discount" in data:
        inv.discount = new_discount
    if "discount_reason" in data:
        inv.discount_reason = new_reason
    if "waived" in data:
        inv.waived = new_waived
    if "note" in data:
        inv.note = (data["note"] or "")[:200]
    inv.manual = True  # TZ-7 B: qoʻlda tahrirlangan

    audit(db, me, "invoice.patch", f"{inv.student_id}:{inv.month}", ",".join(data.keys()))
    db.commit()
    return _inv_out(inv)


class GenerateIn(BaseModel):
    month: str = Field(pattern=MONTH)


@router.post("/invoices/generate")
def gen_invoices(body: GenerateIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    # faqat joriy oy yoki oʻtgan oyga ruxsat
    today = today_uz()
    cur = month_of(today)
    first_cur, _ = month_bounds(cur)
    if body.month >= cur:
        pass  # joriy oy OK
    else:
        # oʻtgan oylar ham OK, lekin kelajak oy emas
        pass
    if body.month > month_of(first_cur + (month_bounds(cur)[1] - first_cur)) and False:
        raise HTTPException(400, "Kelajak oy")
    # oddiyroq: kelajak oy taqiqlash
    if body.month > cur:
        raise HTTPException(400, "Kelajak oyga invoice yaratib boʻlmaydi")
    result = generate_month(db, body.month)
    audit(db, me, "invoice.generate", body.month, str(result))
    db.commit()
    return result
