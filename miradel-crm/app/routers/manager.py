"""Menejer: moliya (oʻquvchi toʻlovlari), oʻqituvchilar maoshi, ish rejasi, dars hisobotlari."""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..finance import effective_fee, month_bounds, month_of, pay_status, today_uz
from ..models import Group, LessonReport, Payment, SalaryPayout, User, WorkPlan
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
    groups = {g.id: g for g in db.scalars(select(Group))}
    tname = {u.id: u.full_name for u in db.scalars(select(User).where(User.is_teacher.is_(True)))}
    paid = dict(db.execute(select(Payment.student_id, func.sum(Payment.amount)).where(Payment.month == m, Payment.voided.is_(False)).group_by(Payment.student_id)).all())
    rows, expected, debtors, unpriced = [], 0, 0, 0
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True)).order_by(User.full_name)):
        fee, p = effective_fee(s, groups), int(paid.get(s.id, 0))
        st = pay_status(fee, p, m, s.fee_day, today)
        if fee > 0:
            expected += fee
            if p < fee:
                debtors += 1
        else:
            unpriced += 1
        g = groups.get(s.group_id)
        rows.append({"id": s.id, "full_name": s.full_name, "login": s.login, "group": g.name if g else "", "fee": fee,
                     "own_fee": s.monthly_fee, "fee_day": s.fee_day, "paid": p, "left": max(0, fee - p), "status": st})
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


def _pay_out(p: Payment) -> dict:
    return {"id": p.id, "month": p.month, "amount": p.amount, "method": p.method, "note": p.note,
            "paid_on": p.paid_on.isoformat(), "voided": p.voided}


@router.post("/payments")
def add_payment(body: PayIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    s = db.get(User, body.student_id)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    p = Payment(student_id=s.id, month=body.month, amount=body.amount, method=body.method, note=body.note.strip(),
                paid_on=today_uz(), created_by=me.id)
    db.add(p)
    audit(db, me, "payment.add", s.login, f"{body.month} {body.amount}")
    db.commit()
    return _pay_out(p)


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


# ---------- Maosh ----------
def _salary_rows(db: Session, m: str):
    first, nxt = month_bounds(m)
    out = []
    for t in db.scalars(select(User).where(User.is_teacher.is_(True), User.active.is_(True)).order_by(User.full_name)):
        gids = [g.id for g in db.scalars(select(Group).where(Group.teacher_id == t.id))]
        lessons = db.scalar(select(func.count()).select_from(
            select(LessonReport.group_id, LessonReport.day).where(LessonReport.teacher_id == t.id, LessonReport.day >= first, LessonReport.day < nxt).distinct().subquery())) or 0
        collected = 0
        if gids and t.salary_mode == "percent":
            collected = int(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).join(User, User.id == Payment.student_id).where(
                Payment.month == m, Payment.voided.is_(False), User.group_id.in_(gids))) or 0)
        if t.salary_mode == "per_lesson":
            amount = lessons * t.salary_rate
        elif t.salary_mode == "percent":
            amount = round(collected * t.salary_rate / 100)
        else:
            amount = t.salary_rate
        paid = int(db.scalar(select(func.coalesce(func.sum(SalaryPayout.amount), 0)).where(SalaryPayout.teacher_id == t.id, SalaryPayout.month == m)) or 0)
        out.append({"id": t.id, "full_name": t.full_name, "mode": t.salary_mode, "rate": t.salary_rate, "lessons": lessons,
                    "collected": collected, "amount": amount, "paid": paid, "balance": amount - paid})
    return out


@router.get("/salary")
def salary(month: Optional[str] = None, db: Session = Depends(get_db)):
    m = _month(month)
    rows = _salary_rows(db, m)
    return {"month": m, "rows": rows, "totals": {"amount": sum(r["amount"] for r in rows), "paid": sum(r["paid"] for r in rows),
                                                  "balance": sum(r["balance"] for r in rows)}}


class SalarySet(BaseModel):
    salary_mode: str = Field(pattern=r"^(per_lesson|percent|fixed)$")
    salary_rate: int = Field(ge=0, le=100_000_000)


@router.patch("/teachers/{tid}/salary")
def set_salary(tid: int, body: SalarySet, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    t = db.get(User, tid)
    if not t or not t.is_teacher:
        raise HTTPException(404, "Oʻqituvchi topilmadi")
    if body.salary_mode == "percent" and body.salary_rate > 100:
        raise HTTPException(400, "Foiz 100 dan oshmasligi kerak")
    t.salary_mode, t.salary_rate = body.salary_mode, body.salary_rate
    audit(db, me, "salary.set", t.login, f"{body.salary_mode}={body.salary_rate}")
    db.commit()
    return {"id": t.id, "salary_mode": t.salary_mode, "salary_rate": t.salary_rate}


class PayoutIn(BaseModel):
    teacher_id: int
    month: str = Field(pattern=MONTH)
    amount: int = Field(ge=1, le=100_000_000)
    note: str = Field(default="", max_length=200)


@router.post("/salary/payouts")
def payout(body: PayoutIn, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    t = db.get(User, body.teacher_id)
    if not t or not t.is_teacher:
        raise HTTPException(404, "Oʻqituvchi topilmadi")
    p = SalaryPayout(teacher_id=t.id, month=body.month, amount=body.amount, note=body.note.strip(), paid_on=today_uz(), created_by=me.id)
    db.add(p)
    audit(db, me, "salary.payout", t.login, f"{body.month} {body.amount}")
    db.commit()
    return {"id": p.id, "amount": p.amount, "month": p.month, "paid_on": p.paid_on.isoformat(), "note": p.note}


@router.get("/salary/payouts")
def payouts(teacher_id: int, month: Optional[str] = None, db: Session = Depends(get_db)):
    stmt = select(SalaryPayout).where(SalaryPayout.teacher_id == teacher_id).order_by(SalaryPayout.id.desc()).limit(50)
    if month:
        stmt = stmt.where(SalaryPayout.month == month)
    return [{"id": p.id, "amount": p.amount, "month": p.month, "paid_on": p.paid_on.isoformat(), "note": p.note} for p in db.scalars(stmt)]


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
