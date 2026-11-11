"""TZ-7: payment settings, discounts, freezes, convergence, reminders, punctuality."""
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..finance import clamp_day, effective_fee, month_of, today_uz
from ..invoices_service import compute_discounts, generate_month, recalc_invoice_discounts
from ..models import (
    BillingFreeze, DiscountPreset, Group, Invoice, Payment, StudentDiscount, User,
)
from ..pay_settings import load_pay_settings, pay_setting, set_pay_setting
from .admin import audit

router = APIRouter(prefix="/api/admin", tags=["payment-settings"], dependencies=[Depends(require_admin)])
MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


# ---------------- A. Settings ----------------

class SettingsIn(BaseModel):
    default_fee_day: Optional[int] = Field(default=None, ge=1, le=28)
    grace_days: Optional[int] = Field(default=None, ge=0, le=15)
    billing_start_month: Optional[str] = Field(default=None, pattern=r"^(\d{4}-(0[1-9]|1[0-2])|)$")
    first_month_mode: Optional[Literal["full", "prorate", "free"]] = None
    prorate_round: Optional[int] = Field(default=None, ge=1, le=100_000)
    remind_days_before: Optional[str] = Field(default=None, max_length=40)
    converge_enabled: Optional[bool] = None
    converge_target_day: Optional[int] = Field(default=None, ge=1, le=28)
    converge_months: Optional[int] = Field(default=None, ge=1, le=12)


def _out_settings(db: Session) -> dict:
    return load_pay_settings(db)


@router.get("/payment-settings")
def get_settings(db: Session = Depends(get_db)):
    return _out_settings(db)


@router.put("/payment-settings")
def put_settings(body: SettingsIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)

    if "remind_days_before" in data and data["remind_days_before"] is not None:
        raw = data["remind_days_before"].strip()
        try:
            parts = [int(x) for x in raw.split(",") if x.strip() != ""]
        except ValueError:
            raise HTTPException(400, "remind_days_before format: \"3,1,0\"")
        if any(p < 0 or p > 60 for p in parts):
            raise HTTPException(400, "Kunlar 0..60 orasida boʻlsin")
        if not parts:
            raise HTTPException(400, "Kamida bitta kun kerak")
        data["remind_days_before"] = ",".join(str(x) for x in sorted(set(parts), reverse=True))

    for key, value in data.items():
        if value is None:
            continue
        if key == "converge_enabled":
            set_pay_setting(db, key, "true" if value else "false")
        elif key == "billing_start_month":
            set_pay_setting(db, key, value or "")
        else:
            set_pay_setting(db, key, str(value))

    audit(db, me, "payment_settings.update", "pay", ",".join(data.keys()))
    db.commit()
    return _out_settings(db)


# ---------------- B. Discount presets ----------------

class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["percent", "amount"]
    value: int = Field(ge=1)
    active: bool = True


class PresetPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    kind: Optional[Literal["percent", "amount"]] = None
    value: Optional[int] = Field(default=None, ge=1)
    active: Optional[bool] = None


def _preset_out(p: DiscountPreset) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "value": p.value, "active": p.active}


def _check_preset_value(kind: str, value: int) -> None:
    if kind == "percent" and not (1 <= value <= 100):
        raise HTTPException(400, "Foiz 1..100 orasida boʻlsin")
    if kind == "amount" and value <= 0:
        raise HTTPException(400, "Summa > 0 boʻlsin")


@router.get("/discount-presets")
def list_presets(db: Session = Depends(get_db)):
    return [_preset_out(p) for p in db.scalars(select(DiscountPreset).order_by(DiscountPreset.name))]


@router.post("/discount-presets")
def create_preset(body: PresetIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_preset_value(body.kind, body.value)
    if db.scalar(select(DiscountPreset.id).where(func.lower(DiscountPreset.name) == body.name.strip().lower())):
        raise HTTPException(400, "Bu nom bilan preset bor")
    p = DiscountPreset(name=body.name.strip(), kind=body.kind, value=body.value, active=body.active)
    db.add(p)
    audit(db, me, "discount_preset.create", p.name, f"{p.kind}={p.value}")
    db.commit()
    return _preset_out(p)


@router.patch("/discount-presets/{pid}")
def patch_preset(pid: int, body: PresetPatch, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(DiscountPreset, pid)
    if not p:
        raise HTTPException(404, "Topilmadi")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        new_name = data["name"].strip()
        if db.scalar(select(DiscountPreset.id).where(
            func.lower(DiscountPreset.name) == new_name.lower(), DiscountPreset.id != pid
        )):
            raise HTTPException(400, "Bu nom bilan preset bor")
        p.name = new_name
    if "kind" in data and data["kind"]:
        p.kind = data["kind"]
    if "value" in data and data["value"] is not None:
        _check_preset_value(p.kind, data["value"])
        p.value = data["value"]
    if "active" in data and data["active"] is not None:
        p.active = data["active"]
    audit(db, me, "discount_preset.update", p.name, ",".join(data.keys()))
    db.commit()
    return _preset_out(p)


@router.delete("/discount-presets/{pid}")
def delete_preset(pid: int, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(DiscountPreset, pid)
    if not p:
        raise HTTPException(404, "Topilmadi")
    p.active = False
    audit(db, me, "discount_preset.deactivate", p.name)
    db.commit()
    return {"ok": True}


# ---------------- B. Student discounts ----------------

class StudentDiscountIn(BaseModel):
    preset_id: Optional[int] = None
    kind: Optional[Literal["percent", "amount"]] = None
    value: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=200)
    from_month: str = Field(pattern=MONTH)
    to_month: Optional[str] = Field(default=None, pattern=MONTH)


def _sd_out(d: StudentDiscount, preset_name: str = "") -> dict:
    return {
        "id": d.id, "student_id": d.student_id, "preset_id": d.preset_id,
        "preset_name": preset_name, "kind": d.kind, "value": d.value,
        "reason": d.reason, "from_month": d.from_month, "to_month": d.to_month,
        "voided": d.voided, "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("/students/{sid}/discounts")
def list_student_discounts(sid: int, db: Session = Depends(get_db)):
    s = db.get(User, sid)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    presets = {p.id: p.name for p in db.scalars(select(DiscountPreset))}
    rows = db.scalars(select(StudentDiscount).where(StudentDiscount.student_id == sid).order_by(StudentDiscount.id.desc()))
    return [_sd_out(d, presets.get(d.preset_id, "")) for d in rows]


@router.post("/students/{sid}/discounts")
def create_student_discount(sid: int, body: StudentDiscountIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(User, sid)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    if body.to_month and body.to_month < body.from_month:
        raise HTTPException(400, "to_month from_month dan katta boʻlsin")
    kind = body.kind
    value = body.value
    if body.preset_id:
        p = db.get(DiscountPreset, body.preset_id)
        if not p or not p.active:
            raise HTTPException(400, "Preset topilmadi yoki faol emas")
        kind = p.kind
        value = p.value
    if kind not in ("percent", "amount") or not value or value < 1:
        raise HTTPException(400, "kind va value kerak (yoki preset_id)")
    _check_preset_value(kind, value)
    d = StudentDiscount(
        student_id=sid, preset_id=body.preset_id,
        kind=kind, value=value, reason=body.reason.strip(),
        from_month=body.from_month, to_month=body.to_month,
        created_by=me.id,
    )
    db.add(d)
    db.flush()
    # TZ-7 B: mavjud invoice'larni qayta hisoblash
    for inv in db.scalars(select(Invoice).where(
        Invoice.student_id == sid,
        Invoice.month >= body.from_month,
        (Invoice.month <= body.to_month) if body.to_month else True,
        Invoice.manual.is_(False),
        Invoice.waived.is_(False),
    )):
        recalc_invoice_discounts(db, sid, inv.month)
    audit(db, me, "student_discount.create", s.login, f"{kind}={value} {body.from_month}..{body.to_month or '∞'}")
    db.commit()
    return _sd_out(d)


@router.post("/students/{sid}/discounts/{did}/void")
def void_student_discount(sid: int, did: int, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(StudentDiscount, did)
    if not d or d.student_id != sid:
        raise HTTPException(404, "Topilmadi")
    d.voided = True
    # TZ-7 B: mavjud invoice'larni qayta hisoblash
    for inv in db.scalars(select(Invoice).where(
        Invoice.student_id == sid,
        Invoice.month >= d.from_month,
        (Invoice.month <= d.to_month) if d.to_month else True,
        Invoice.manual.is_(False),
        Invoice.waived.is_(False),
    )):
        recalc_invoice_discounts(db, sid, inv.month)
    audit(db, me, "student_discount.void", str(did))
    db.commit()
    return {"ok": True}


# ---------------- B. Billing freezes ----------------

class FreezeIn(BaseModel):
    from_month: str = Field(pattern=MONTH)
    to_month: str = Field(pattern=MONTH)
    reason: str = Field(default="", max_length=200)


def _fz_out(f: BillingFreeze) -> dict:
    return {"id": f.id, "student_id": f.student_id, "from_month": f.from_month,
            "to_month": f.to_month, "reason": f.reason, "voided": f.voided,
            "created_at": f.created_at.isoformat() if f.created_at else None}


@router.get("/students/{sid}/freezes")
def list_student_freezes(sid: int, db: Session = Depends(get_db)):
    s = db.get(User, sid)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    rows = db.scalars(select(BillingFreeze).where(BillingFreeze.student_id == sid).order_by(BillingFreeze.id.desc()))
    return [_fz_out(f) for f in rows]


@router.post("/students/{sid}/freezes")
def create_freeze(sid: int, body: FreezeIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(User, sid)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    if body.to_month < body.from_month:
        raise HTTPException(400, "to_month from_month dan katta boʻlsin")

    # TZ-7 B: toʻqnashuvlarni tekshirish
    existing_invs = list(db.scalars(select(Invoice).where(
        Invoice.student_id == sid,
        Invoice.month >= body.from_month,
        Invoice.month <= body.to_month,
    )))
    paid_by_month: dict[str, int] = {}
    if existing_invs:
        paid_rows = db.execute(
            select(Payment.month, func.sum(Payment.amount)).where(
                Payment.student_id == sid,
                Payment.month >= body.from_month,
                Payment.month <= body.to_month,
                Payment.voided.is_(False),
            ).group_by(Payment.month)
        ).all()
        paid_by_month = {m: int(a or 0) for m, a in paid_rows}

    conflicts = [inv.month for inv in existing_invs if (paid_by_month.get(inv.month, 0) > 0)]
    if conflicts:
        raise HTTPException(409, f"Bu oylarda toʻlov bor: {', '.join(sorted(conflicts))}")

    for inv in existing_invs:
        inv.waived = True
        inv.discount_reason = (inv.discount_reason + ", Muzlatilgan").strip(", ")[:200]

    f = BillingFreeze(
        student_id=sid, from_month=body.from_month, to_month=body.to_month,
        reason=body.reason.strip(), created_by=me.id,
    )
    db.add(f)
    audit(db, me, "student_freeze.create", s.login, f"{body.from_month}..{body.to_month}")
    db.commit()
    return _fz_out(f)


@router.post("/students/{sid}/freezes/{fid}/void")
def void_freeze(sid: int, fid: int, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(BillingFreeze, fid)
    if not f or f.student_id != sid:
        raise HTTPException(404, "Topilmadi")
    f.voided = True
    audit(db, me, "student_freeze.void", str(fid))
    db.commit()
    return {"ok": True}


# ---------------- D. Convergence preview + reset ----------------

@router.get("/payment-settings/convergence-preview")
def convergence_preview(db: Session = Depends(get_db)):
    cfg = load_pay_settings(db)
    target = cfg["converge_target_day"]
    months = cfg["converge_months"]
    groups = {g.id: g for g in db.scalars(select(Group))}
    out = []
    distribution: dict[int, int] = {}

    current_month = month_of(today_uz())
    # "oldest" keyingi months uchun generatsiya taxmin
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True)).order_by(User.full_name)):
        fee = effective_fee(s, groups)
        if fee <= 0:
            continue
        # oldingi invoice.due_day
        prev = db.scalar(select(Invoice).where(
            Invoice.student_id == s.id,
            Invoice.month < current_month,
        ).order_by(Invoice.month.desc()).limit(1))
        cur_inv = db.scalar(select(Invoice).where(
            Invoice.student_id == s.id, Invoice.month == current_month
        ))
        d_prev = (cur_inv.due_day if cur_inv and cur_inv.due_day else
                  (prev.due_day if prev and prev.due_day else s.fee_day))
        origin = s.fee_day_origin if s.fee_day_origin is not None else d_prev
        step = -(-(origin - target) // months) if origin > target else 0

        planned = [d_prev]
        for _ in range(months):
            if planned[-1] <= target:
                planned.append(planned[-1])
            else:
                planned.append(max(target, planned[-1] - step))

        out.append({
            "student_id": s.id, "full_name": s.full_name,
            "group": groups.get(s.group_id).name if s.group_id in groups else "",
            "fee": fee, "current_day": d_prev, "origin": origin,
            "planned": planned[1:],
        })
        distribution[d_prev] = distribution.get(d_prev, 0) + 1

    return {
        "target": target, "months": months,
        "distribution": distribution,
        "students": out,
    }


class ResetIn(BaseModel):
    student_ids: Optional[list[int]] = None


@router.post("/payment-settings/convergence-reset")
def convergence_reset(body: ResetIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(User).where(User.is_student.is_(True))
    if body.student_ids:
        stmt = stmt.where(User.id.in_(body.student_ids[:500]))
    count = 0
    for s in db.scalars(stmt):
        if s.fee_day_origin is not None:
            s.fee_day_origin = None
            count += 1
    audit(db, me, "convergence.reset", "fee_day_origin", f"count={count}")
    db.commit()
    return {"cleared": count}


# ---------------- F. Bulk student update ----------------

class BulkStudentIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    monthly_fee: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    fee_day: Optional[int] = Field(default=None, ge=1, le=31)


@router.post("/payment-settings/bulk-student")
def bulk_student(body: BulkStudentIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.monthly_fee is None and body.fee_day is None:
        raise HTTPException(400, "monthly_fee yoki fee_day dan biri kerak")
    ids = list({x for x in body.ids})
    students = list(db.scalars(select(User).where(User.id.in_(ids), User.is_student.is_(True))))
    if not students:
        raise HTTPException(404, "Oʻquvchilar topilmadi")
    updated = 0
    for s in students:
        if body.monthly_fee is not None:
            s.monthly_fee = body.monthly_fee
        if body.fee_day is not None:
            s.fee_day = body.fee_day
            s.fee_day_origin = body.fee_day  # TZ-7 D: qoʻlda oʻzgartirish originni reset qiladi
        updated += 1
    audit(db, me, "bulk_student.update", f"count={updated}", f"fee={body.monthly_fee} day={body.fee_day}")
    db.commit()
    return {"updated": updated}


# ---------------- D. Punctuality report ----------------

@router.get("/payments/punctuality")
def punctuality(month: Optional[str] = None, db: Session = Depends(get_db)):
    m = month or month_of(today_uz())
    if len(m) != 7:
        raise HTTPException(400, "Oy formati: YYYY-MM")
    groups = {g.id: g for g in db.scalars(select(Group))}
    rows = []
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True)).order_by(User.full_name)):
        inv = db.scalar(select(Invoice).where(Invoice.student_id == s.id, Invoice.month == m))
        due_day = inv.due_day if inv and inv.due_day else s.fee_day
        due_date = clamp_day(m, due_day)
        # birinchi toʻlov
        first_pay = db.scalar(select(func.min(Payment.paid_on)).where(
            Payment.student_id == s.id, Payment.month == m, Payment.voided.is_(False)
        ))
        if first_pay:
            days_late = max(0, (first_pay - due_date).days)
            actual_paid_on = first_pay.isoformat()
        else:
            days_late = None
            actual_paid_on = None
        rows.append({
            "student_id": s.id, "full_name": s.full_name,
            "group": groups.get(s.group_id).name if s.group_id in groups else "",
            "planned_due_day": due_day, "planned_due_date": due_date.isoformat(),
            "actual_paid_on": actual_paid_on, "days_late": days_late,
        })
    return {"month": m, "rows": rows}


# ---------------- E. Reminders ----------------

@router.get("/payments/reminders")
def reminders(day: Optional[str] = None, db: Session = Depends(get_db)):
    d = date.fromisoformat(day) if day else today_uz()
    cfg = load_pay_settings(db)
    try:
        offsets = [int(x) for x in cfg["remind_days_before"].split(",") if x.strip()]
    except ValueError:
        offsets = [3, 1, 0]

    m = month_of(d)
    groups = {g.id: g for g in db.scalars(select(Group))}
    upcoming = []
    overdue = []

    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True))):
        inv = db.scalar(select(Invoice).where(Invoice.student_id == s.id, Invoice.month == m))
        due_day = inv.due_day if inv and inv.due_day else s.fee_day
        due_date = clamp_day(m, due_day)

        if inv:
            fee = 0 if inv.waived else max(0, inv.amount_due - inv.discount)
        else:
            fee = effective_fee(s, groups)
        if fee <= 0:
            continue

        paid = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.student_id == s.id, Payment.month == m, Payment.voided.is_(False)
        )) or 0
        left = max(0, fee - paid)
        if left <= 0:
            continue

        g = groups.get(s.group_id)
        base = {
            "student_id": s.id, "full_name": s.full_name,
            "group": g.name if g else "",
            "parent_phone": s.parent_phone or "",
            "phone": s.phone or "",
            "due_date": due_date.isoformat(),
            "left": left,
        }
        for k in offsets:
            if due_date == d + timedelta(days=k):
                upcoming.append({**base, "offset_days": k})
                break
        if due_date < d:
            overdue.append({**base, "days_overdue": (d - due_date).days})

    upcoming.sort(key=lambda x: x["offset_days"])
    overdue.sort(key=lambda x: x["days_overdue"], reverse=True)
    return {"day": d.isoformat(), "month": m, "upcoming": upcoming, "overdue": overdue}


# ---------------- Manager generate helper (also exposed under /api/admin for TZ-7 admin panel) ----------------

class AdminGenIn(BaseModel):
    month: str = Field(pattern=MONTH)


@router.post("/payments/invoices/generate")
def admin_generate(body: AdminGenIn, me: User = Depends(require_admin), db: Session = Depends(get_db)):
    result = generate_month(db, body.month)
    audit(db, me, "invoice.generate", body.month, str(result))
    db.commit()
    return result
