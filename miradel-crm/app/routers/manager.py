"""Menejer: moliya, oʻqituvchilar maoshi, ish rejasi, dars hisobotlari."""
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..finance import clamp_day, effective_fee, month_bounds, month_of, pay_status, today_uz
from ..invoices_service import generate_month
from ..models import (
    Group, Invoice, LessonReport, Payment, SalaryAdjustment, SalaryPayout, User, WorkPlan
)
from ..pay_settings import load_pay_settings
from ..receipts_service import generate_receipt_no
from ..salary_service import get_salary_rows, get_salary_sheet
from .admin import audit

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


def finance_user(u: User = Depends(current_user)) -> User:
    if not (u.is_manager or u.is_admin):
        raise HTTPException(403, "Faqat menejer uchun")
    return u


router = APIRouter(prefix="/api/manager", tags=["manager"], dependencies=[Depends(finance_user)])


def _month(m: Optional[str]) -> str:
    if not m:
        return month_of(today_uz())
    return m


# ---------- Moliya ----------
@router.get("/finance")
def finance(month: Optional[str] = None, db: Session = Depends(get_db)):
    m = _month(month)
    if len(m) != 7:
        raise HTTPException(400, "Oy formati: YYYY-MM")
    today = today_uz()
    cfg = load_pay_settings(db)
    grace = cfg["grace_days"]

    groups = {g.id: g for g in db.scalars(select(Group))}
    tname = {u.id: u.full_name for u in db.scalars(select(User).where(User.is_teacher.is_(True)))}
    paid = dict(db.execute(select(Payment.student_id, func.sum(Payment.amount)).where(Payment.month == m, Payment.voided.is_(False)).group_by(Payment.student_id)).all())
    invoices = {inv.student_id: inv for inv in db.scalars(select(Invoice).where(Invoice.month == m))}

    rows, expected, debtors, unpriced = [], 0, 0, 0
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True)).order_by(User.full_name)):
        inv = invoices.get(s.id)
        if inv:
            fee = 0 if inv.waived else max(0, inv.amount_due - inv.discount)
            due_day = inv.due_day if inv.due_day else s.fee_day
        else:
            fee = effective_fee(s, groups)
            due_day = s.fee_day
        p = int(paid.get(s.id, 0))
        st = pay_status(fee, p, m, due_day, today, grace)
        if fee > 0:
            expected += fee
            if p < fee:
                debtors += 1
        else:
            unpriced += 1
        g = groups.get(s.group_id)
        rows.append({"id": s.id, "full_name": s.full_name, "login": s.login, "group": g.name if g else "", "fee": fee,
                     "own_fee": s.monthly_fee, "fee_day": due_day, "paid": p, "left": max(0, fee - p), "status": st})
    collected = int(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.month == m, Payment.voided.is_(False))) or 0)
    return {"month": m, "today": today.isoformat(),
            "totals": {"expected": expected, "collected": collected, "debtors": debtors, "unpriced": unpriced},
            "rows": rows,
            "groups": [{"id": g.id, "name": g.name, "monthly_fee": g.monthly_fee, "teacher_name": tname.get(g.teacher_id, "")} for g in sorted(groups.values(), key=lambda x: x.name) if g.active]}


class PayIn(BaseModel):
    student_id: int
    month: str = Field(pattern=MONTH)
    amount: int = Field(ge=1, le=100_000_000)
    method: str = Field(default="cash", pattern=r"^(cash|card|transfer)$")
    note: str = Field(default="", max_length=200)
    paid_on: Optional[date] = None
    course: Optional[str] = Field(default=None, max_length=80)
    allocate_oldest: bool = False


def _pay_out(p: Payment) -> dict:
    return {"id": p.id, "month": p.month, "amount": p.amount, "method": p.method, "note": p.note,
            "paid_on": p.paid_on.isoformat(), "voided": p.voided, "course": p.course or ""}


@router.post("/payments")
def add_payment(body: PayIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    s = db.get(User, body.student_id)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")

    today = today_uz()
    paid_on = body.paid_on if body.paid_on else today
    if paid_on > today:
        raise HTTPException(400, "Toʻlov sanasi kelajakda boʻlishi mumkin emas")
    if paid_on < today - timedelta(days=60):
        raise HTTPException(400, "Toʻlov sanasi 60 kundan eski boʻlishi mumkin emas")

    course = body.course.strip() if body.course else ""
    if not course:
        g = db.get(Group, s.group_id) if s.group_id else None
        course = (g.course if g and g.course else "")

    created_payments = []
    
    if body.allocate_oldest:
        remainder = body.amount
        # Fetch unpaid invoices oldest first
        unpaid_invoices = db.scalars(select(Invoice).where(Invoice.student_id == s.id, Invoice.waived.is_(False)).order_by(Invoice.month)).all()
        for inv in unpaid_invoices:
            if remainder <= 0:
                break
            # Calculate already paid for this month
            already_paid = int(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.student_id == s.id, Payment.month == inv.month, Payment.voided.is_(False))) or 0)
            net_due = max(0, inv.amount_due - inv.discount)
            left = net_due - already_paid
            if left > 0:
                alloc = min(left, remainder)
                remainder -= alloc
                p = Payment(
                    student_id=s.id, month=inv.month, amount=alloc, method=body.method,
                    note=body.note.strip(), paid_on=paid_on, course=course[:80], created_by=me.id
                )
                p.receipt_no = generate_receipt_no(db, paid_on)
                db.add(p)
                db.flush()
                created_payments.append(p)
        
        if remainder > 0:
            # leftover goes to the selected month
            p = Payment(
                student_id=s.id, month=body.month, amount=remainder, method=body.method,
                note=body.note.strip(), paid_on=paid_on, course=course[:80], created_by=me.id
            )
            p.receipt_no = generate_receipt_no(db, paid_on)
            db.add(p)
            db.flush()
            created_payments.append(p)
    else:
        p = Payment(
            student_id=s.id, month=body.month, amount=body.amount, method=body.method,
            note=body.note.strip(), paid_on=paid_on, course=course[:80], created_by=me.id
        )
        p.receipt_no = generate_receipt_no(db, paid_on)
        db.add(p)
        db.flush()
        created_payments.append(p)

    audit(db, me, "payment.add", s.login, f"{body.month} {body.amount} alloc={body.allocate_oldest}")
    db.commit()

    if not created_payments:
        raise HTTPException(400, "Toʻlov yaratilmadi")

    first = created_payments[0]
    out = _pay_out(first)
    if body.allocate_oldest:
        out["allocations"] = [{"month": p.month, "amount": p.amount, "payment_id": p.id} for p in created_payments]
    return out


@router.get("/payments")
def payments(student_id: int, limit: int = 30, db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).where(Payment.student_id == student_id).order_by(Payment.id.desc()).limit(min(limit, 100)))
    return [_pay_out(p) for p in rows]


@router.post("/payments/{pid}/void")
def void_payment(pid: int, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    p = db.get(Payment, pid)
    if not p:
        raise HTTPException(404, "Topilmadi")
    p.voided = True
    audit(db, me, "payment.void", str(p.student_id), f"{p.month} {p.amount}")
    db.commit()
    return _pay_out(p)


@router.get("/payments/{pid}/receipt")
def payment_receipt(pid: int, db: Session = Depends(get_db)):
    p = db.get(Payment, pid)
    if not p:
        raise HTTPException(404, "Topilmadi")
    s = db.get(User, p.student_id)
    g = db.get(Group, s.group_id) if s and s.group_id else None
    cashier = db.get(User, p.created_by) if p.created_by else None
    return {
        "receipt_no": p.receipt_no or "—",
        "student": s.full_name if s else "",
        "group": g.name if g else "",
        "month": p.month,
        "amount": p.amount,
        "method": p.method,
        "paid_on": p.paid_on.isoformat(),
        "cashier": cashier.full_name if cashier else "",
        "note": p.note,
        "voided": p.voided
    }


class FeeIn(BaseModel):
    monthly_fee: int = Field(ge=0, le=100_000_000)
    fee_day: Optional[int] = Field(default=None, ge=1, le=31)


@router.patch("/students/{sid}/fee")
def set_student_fee(sid: int, body: FeeIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    s = db.get(User, sid)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    s.monthly_fee = body.monthly_fee
    if body.fee_day:
        s.fee_day = body.fee_day
        s.fee_day_origin = body.fee_day
    audit(db, me, "fee.student", s.login, f"{body.monthly_fee}/{s.fee_day}")
    db.commit()
    return {"id": s.id, "monthly_fee": s.monthly_fee, "fee_day": s.fee_day}


class GroupFeeIn(BaseModel):
    monthly_fee: int = Field(ge=0, le=100_000_000)


@router.patch("/groups/{gid}/fee")
def set_group_fee(gid: int, body: GroupFeeIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    g = db.get(Group, gid)
    if not g:
        raise HTTPException(404, "Guruh topilmadi")
    g.monthly_fee = body.monthly_fee
    audit(db, me, "fee.group", g.name, str(body.monthly_fee))
    db.commit()
    return {"id": g.id, "monthly_fee": g.monthly_fee}


# ---------- Invoices ----------
@router.get("/invoices")
def get_invoices(month: Optional[str] = None, student_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(Invoice).order_by(Invoice.month.desc(), Invoice.id.desc()).limit(1000)
    if month:
        stmt = stmt.where(Invoice.month == month)
    if student_id:
        stmt = stmt.where(Invoice.student_id == student_id)
    invs = list(db.scalars(stmt))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({i.student_id for i in invs})))}
    groups = {g.id: g for g in db.scalars(select(Group))}
    
    return [{
        "id": inv.id, "student_id": inv.student_id,
        "student_name": users[inv.student_id].full_name if inv.student_id in users else "",
        "group_name": groups[users[inv.student_id].group_id].name if inv.student_id in users and users[inv.student_id].group_id in groups else "",
        "month": inv.month, "amount_due": inv.amount_due, "discount": inv.discount,
        "discount_reason": inv.discount_reason, "waived": inv.waived,
        "note": inv.note, "manual": inv.manual, "due_day": inv.due_day,
        "net": 0 if inv.waived else max(0, inv.amount_due - inv.discount)
    } for inv in invs]


class InvPatch(BaseModel):
    discount: Optional[int] = Field(default=None, ge=0)
    discount_reason: Optional[str] = Field(default=None, max_length=200)
    waived: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=200)


@router.patch("/invoices/{iid}")
def patch_invoice(iid: int, body: InvPatch, me: User = Depends(finance_user), db: Session = Depends(get_db)):
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
        
    if "discount" in data: inv.discount = new_discount
    if "discount_reason" in data: inv.discount_reason = new_reason
    if "waived" in data: inv.waived = new_waived
    if "note" in data: inv.note = (data["note"] or "")[:200]
    inv.manual = True
    
    audit(db, me, "invoice.patch", f"{inv.student_id}:{inv.month}", ",".join(data.keys()))
    db.commit()
    return {"ok": True}


class GenIn(BaseModel):
    month: str = Field(pattern=MONTH)


@router.post("/invoices/generate")
def gen_invoices(body: GenIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    result = generate_month(db, body.month)
    audit(db, me, "invoice.generate", body.month, str(result))
    db.commit()
    return result


# ---------- Debts ----------
@router.get("/debts")
def get_debts(upto: Optional[str] = None, group_id: Optional[int] = None, q: Optional[str] = None, db: Session = Depends(get_db)):
    m = upto or month_of(today_uz())
    if len(m) != 7:
        raise HTTPException(400, "Oy formati: YYYY-MM")

    stmt = select(User).where(User.is_student.is_(True), User.active.is_(True))
    if group_id:
        stmt = stmt.where(User.group_id == group_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.phone.ilike(like)))
        
    students = list(db.scalars(stmt.order_by(User.full_name)))
    groups = {g.id: g for g in db.scalars(select(Group))}
    
    out = []
    for s in students:
        invs = db.scalars(select(Invoice).where(Invoice.student_id == s.id, Invoice.month <= m).order_by(Invoice.month)).all()
        if not invs:
            continue
            
        months_data = []
        total_left = 0
        
        paid_by_month = dict(db.execute(
            select(Payment.month, func.sum(Payment.amount))
            .where(Payment.student_id == s.id, Payment.voided.is_(False))
            .group_by(Payment.month)
        ).all())
        
        for inv in invs:
            due = 0 if inv.waived else max(0, inv.amount_due - inv.discount)
            paid = int(paid_by_month.get(inv.month, 0))
            left = max(0, due - paid)
            if left > 0:
                months_data.append({"month": inv.month, "due": due, "paid": paid, "left": left})
                total_left += left
                
        if total_left > 0:
            g = groups.get(s.group_id)
            out.append({
                "student_id": s.id, "student": s.full_name, "group": g.name if g else "",
                "phone": s.phone, "parent_phone": s.parent_phone,
                "months": months_data, "total_left": total_left
            })
            
    out.sort(key=lambda x: x["total_left"], reverse=True)
    totals = sum(x["total_left"] for x in out)
    
    return {"upto": m, "rows": out, "total_left": totals}


# ---------- Maosh ----------
@router.get("/salary")
def salary(month: Optional[str] = None, db: Session = Depends(get_db)):
    m = _month(month)
    rows = get_salary_rows(db, m)
    return {
        "month": m, "rows": rows,
        "totals": {
            "amount": sum(r["amount"] for r in rows),
            "paid": sum(r["paid"] for r in rows),
            "balance": sum(r["balance"] for r in rows),
            "adjustments": sum(r["adjustments"] for r in rows),
            "amount_total": sum(r["amount_total"] for r in rows),
            "balance_total": sum(r["balance_total"] for r in rows)
        }
    }


@router.get("/salary/sheet")
def salary_sheet(teacher_id: int, month: str, db: Session = Depends(get_db)):
    if len(month) != 7:
        raise HTTPException(400, "Oy formati: YYYY-MM")
    sheet = get_salary_sheet(db, teacher_id, month)
    if not sheet:
        raise HTTPException(404, "Oʻqituvchi topilmadi")
    return sheet


class AdjIn(BaseModel):
    teacher_id: int
    month: str = Field(pattern=MONTH)
    amount: int = Field(...)
    reason: str = Field(min_length=3, max_length=200)

@router.get("/salary/adjustments")
def list_adjustments(teacher_id: int, month: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(SalaryAdjustment).where(
        SalaryAdjustment.teacher_id == teacher_id, SalaryAdjustment.month == month
    ).order_by(SalaryAdjustment.id.desc())).all()
    return [{"id": a.id, "amount": a.amount, "reason": a.reason, "voided": a.voided, "date": a.created_at.isoformat()} for a in rows]

@router.post("/salary/adjustments")
def add_adjustment(body: AdjIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    t = db.get(User, body.teacher_id)
    if not t or not t.is_teacher:
        raise HTTPException(404, "Oʻqituvchi topilmadi")
    a = SalaryAdjustment(
        teacher_id=body.teacher_id, month=body.month, amount=body.amount, reason=body.reason.strip(), created_by=me.id
    )
    db.add(a)
    audit(db, me, "salary.adjustment", t.login, f"{body.month} {body.amount} {body.reason}")
    db.commit()
    return {"id": a.id}

@router.post("/salary/adjustments/{aid}/void")
def void_adjustment(aid: int, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    a = db.get(SalaryAdjustment, aid)
    if not a:
        raise HTTPException(404, "Topilmadi")
    a.voided = True
    audit(db, me, "salary.adjustment.void", str(a.id))
    db.commit()
    return {"ok": True}


# ---------- Ish rejasi ----------
class PlanIn(BaseModel):
    teacher_id: int
    title: str = Field(min_length=2, max_length=200)
    due_date: Optional[date] = None


class PlanPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    due_date: Optional[date] = None
    status: Optional[str] = Field(default=None, pattern=r"^(todo|done|cancelled)$")


def _plan_out(p: WorkPlan, names: dict) -> dict:
    return {"id": p.id, "teacher_id": p.teacher_id, "teacher_name": names.get(p.teacher_id, ""), "title": p.title,
            "due_date": p.due_date.isoformat() if p.due_date else None, "status": p.status}


@router.get("/teachers")
def teachers(db: Session = Depends(get_db)):
    return [{"id": u.id, "full_name": u.full_name} for u in db.scalars(select(User).where(User.is_teacher.is_(True), User.active.is_(True)).order_by(User.full_name))]


@router.get("/plans")
def plans(status: Optional[str] = None, db: Session = Depends(get_db)):
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.is_teacher.is_(True)))}
    stmt = select(WorkPlan).order_by(WorkPlan.id.desc()).limit(200)
    if status:
        stmt = stmt.where(WorkPlan.status == status)
    return [_plan_out(p, names) for p in db.scalars(stmt)]


@router.post("/plans")
def add_plan(body: PlanIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    t = db.get(User, body.teacher_id)
    if not t or not t.is_teacher:
        raise HTTPException(404, "Oʻqituvchi topilmadi")
    p = WorkPlan(teacher_id=t.id, title=body.title.strip(), due_date=body.due_date, created_by=me.id)
    db.add(p)
    audit(db, me, "plan.add", t.login, body.title)
    db.commit()
    return _plan_out(p, {t.id: t.full_name})


@router.patch("/plans/{pid}")
def patch_plan(pid: int, body: PlanPatch, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    p = db.get(WorkPlan, pid)
    if not p:
        raise HTTPException(404, "Topilmadi")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    if data.get("status") == "done" and not p.done_at:
        p.done_at = datetime.now(timezone.utc)
    audit(db, me, "plan.update", str(p.id), ",".join(data.keys()))
    db.commit()
    t = db.get(User, p.teacher_id)
    return _plan_out(p, {t.id: t.full_name} if t else {})


# ---------- Dars hisobotlari ----------
@router.get("/reports")
def reports(limit: int = 40, db: Session = Depends(get_db)):
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.is_teacher.is_(True)))}
    gm = {g.id: g.name for g in db.scalars(select(Group))}
    rows = db.scalars(select(LessonReport).order_by(LessonReport.id.desc()).limit(min(limit, 100)))
    return [{"id": r.id, "teacher_name": names.get(r.teacher_id, ""), "group_name": gm.get(r.group_id, ""), "day": r.day.isoformat(),
             "topic": r.topic, "notes": r.notes} for r in rows]
