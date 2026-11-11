"""TZ-3: Reports, dashboard, and student progress."""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..finance import clamp_day, effective_fee, month_bounds, month_of, pay_status, today_uz
from ..models import (
    Announcement, Attendance, Group, Invoice, LessonReport, Payment, PointsLedger,
    Submission, Task, User, WorkPlan,
)
from ..pay_settings import load_pay_settings
from .content import get_setting
from .manager import finance_user

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(finance_user)])


def _csv_safe(v: str) -> str:
    if v and v[0] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def _csv_response(rows: list, filename: str, header: list) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow([_csv_safe(str(c)) if c is not None else "" for c in r])
    body = "\ufeff" + buf.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------- Dashboard ----------------

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today = today_uz()
    m = month_of(today)
    first_day, _ = month_bounds(m)
    today_iso_weekday = today.isoweekday()  # 1=Mon..7=Sun

    # Students
    active_students = db.scalar(select(func.count(User.id)).where(User.is_student.is_(True), User.active.is_(True))) or 0
    inactive_students = db.scalar(select(func.count(User.id)).where(User.is_student.is_(True), User.active.is_(False))) or 0
    no_group_students = db.scalar(select(func.count(User.id)).where(User.is_student.is_(True), User.active.is_(True), User.group_id.is_(None))) or 0
    
    # Yangi (shu oyda boshlangan, TZ-7 dagi `started_on` yoki zaxira `created_at` bo'yicha)
    new_this_month = db.scalar(select(func.count(User.id)).where(
        User.is_student.is_(True), User.active.is_(True),
        or_(
            and_(User.started_on.is_not(None), User.started_on >= first_day),
            and_(User.started_on.is_(None), func.date(User.created_at) >= first_day)
        )
    )) or 0

    # Groups
    active_groups = db.scalar(select(func.count(Group.id)).where(Group.active.is_(True))) or 0
    without_teacher = db.scalar(select(func.count(Group.id)).where(Group.active.is_(True), Group.teacher_id.is_(None))) or 0

    # Attendance Today
    groups_with_lesson = []
    missing = []
    marked = 0
    for g in db.scalars(select(Group).where(Group.active.is_(True))):
        if str(today_iso_weekday) in (g.days or ""):
            groups_with_lesson.append(g)
            att_count = db.scalar(select(func.count(Attendance.id)).where(Attendance.group_id == g.id, Attendance.day == today)) or 0
            if att_count > 0:
                marked += 1
            else:
                teacher = db.get(User, g.teacher_id) if g.teacher_id else None
                missing.append({"group_id": g.id, "group": g.name, "teacher": teacher.full_name if teacher else ""})
                
    # Payments this month
    cfg = load_pay_settings(db)
    grace = cfg["grace_days"]
    groups = {g.id: g for g in db.scalars(select(Group))}
    invoices = {inv.student_id: inv for inv in db.scalars(select(Invoice).where(Invoice.month == m))}
    paid_map = dict(db.execute(select(Payment.student_id, func.sum(Payment.amount)).where(Payment.month == m, Payment.voided.is_(False)).group_by(Payment.student_id)).all())
    
    expected = 0
    collected = int(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.month == m, Payment.voided.is_(False))) or 0)
    debtors = 0
    
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True))):
        inv = invoices.get(s.id)
        if inv:
            fee = 0 if inv.waived else max(0, inv.amount_due - inv.discount)
            due_day = inv.due_day if inv.due_day else s.fee_day
        else:
            fee = effective_fee(s, groups)
            due_day = s.fee_day
        p = int(paid_map.get(s.id, 0))
        st = pay_status(fee, p, m, due_day, today, grace)
        if fee > 0:
            expected += fee
            if p < fee:
                debtors += 1

    # At-risk students
    at_risk = db.scalar(select(func.count(User.id)).where(User.is_student.is_(True), User.active.is_(True))) or 0  # Placeholder, will be calculated properly below
    # Actually let's calculate using the progress logic
    risk_att_pct = int(get_setting(db, "risk_attendance_percent", "60"))
    risk_inact_days = int(get_setting(db, "risk_inactive_days", "14"))
    
    att_stats = dict(db.execute(
        select(Attendance.student_id, func.count(Attendance.id))
        .where(Attendance.day >= first_day, Attendance.day <= today, Attendance.status == "present")
        .group_by(Attendance.student_id)
    ).all())
    total_marks = dict(db.execute(
        select(Attendance.student_id, func.count(Attendance.id))
        .where(Attendance.day >= first_day, Attendance.day <= today)
        .group_by(Attendance.student_id)
    ).all())
    
    risk_count = 0
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True))):
        p = att_stats.get(s.id, 0)
        tot = total_marks.get(s.id, 0)
        at_risk_flag = False
        if tot >= 4:
            if (p / tot * 100) < risk_att_pct:
                at_risk_flag = True
        if not at_risk_flag:
            # last activity
            last_act = db.scalar(
                select(func.max(Attendance.day)).where(Attendance.student_id == s.id)
            )
            if not last_act or (today - last_act).days >= risk_inact_days:
                at_risk_flag = True
        if at_risk_flag:
            risk_count += 1

    # Inactive teachers
    inactive_teachers = []
    since = today - timedelta(days=14)
    for t in db.scalars(select(User).where(User.is_teacher.is_(True), User.active.is_(True))):
        if db.scalar(select(func.count(Group.id)).where(Group.teacher_id == t.id, Group.active.is_(True))) > 0:
            last_rep = db.scalar(select(func.max(LessonReport.day)).where(LessonReport.teacher_id == t.id))
            if not last_rep or last_rep < since:
                inactive_teachers.append({"teacher": t.full_name, "last_report_day": last_rep.isoformat() if last_rep else None})

    return {
        "today": today.isoformat(),
        "students": {"active": active_students, "inactive": inactive_students, "no_group": no_group_students, "new_this_month": new_this_month},
        "groups": {"active": active_groups, "without_teacher": without_teacher},
        "attendance_today": {"groups_with_lesson": len(groups_with_lesson), "marked": marked, "missing": missing},
        "payments_this_month": {"expected": expected, "collected": collected, "debtors": debtors},
        "at_risk_students": risk_count,
        "inactive_teachers": inactive_teachers,
    }


# ---------------- Payments report ----------------

@router.get("/payments")
def report_payments(
    month: Optional[str] = None,
    format: Literal["json", "csv"] = "json",
    db: Session = Depends(get_db),
):
    m = month or month_of(today_uz())
    if len(m) != 7:
        raise HTTPException(400, "Oy formati: YYYY-MM")

    pays = list(db.scalars(select(Payment).where(Payment.month == m).order_by(Payment.paid_on.desc(), Payment.id.desc())))
    students = {u.id: u for u in db.scalars(select(User).where(User.id.in_({p.student_id for p in pays})))}
    groups = {g.id: g for g in db.scalars(select(Group))}

    by_method = {}
    by_day = {}
    non_voided = []
    voided = []
    total = 0

    for p in pays:
        s = students.get(p.student_id)
        g = groups.get(s.group_id) if s and s.group_id else None
        item = {
            "id": p.id, "student": s.full_name if s else "", "group": g.name if g else "",
            "amount": p.amount, "method": p.method, "note": p.note,
            "paid_on": p.paid_on.isoformat(), "course": p.course,
        }
        if p.voided:
            voided.append(item)
        else:
            non_voided.append(item)
            total += p.amount
            by_method[p.method] = by_method.get(p.method, 0) + p.amount
            by_day[p.paid_on.isoformat()] = by_day.get(p.paid_on.isoformat(), 0) + p.amount

    if format == "csv":
        header = ["ID", "Oʻquvchi", "Guruh", "Summa", "Usul", "Kurs", "Toʻlov sanasi", "Izoh"]
        rows = [[x["id"], x["student"], x["group"], x["amount"], x["method"], x["course"], x["paid_on"], x["note"]] for x in non_voided]
        return _csv_response(rows, f"tolovlar-{m}.csv", header)

    return {
        "month": m, "total": total,
        "by_method": by_method, "by_day": by_day,
        "non_voided": non_voided, "voided": voided,
    }


# ---------------- Teachers report ----------------

@router.get("/teachers")
def report_teachers(
    month: Optional[str] = None,
    format: Literal["json", "csv"] = "json",
    db: Session = Depends(get_db),
):
    m = month or month_of(today_uz())
    first, nxt = month_bounds(m)

    rows = []
    for t in db.scalars(select(User).where(User.is_teacher.is_(True), User.active.is_(True)).order_by(User.full_name)):
        gids = [g.id for g in db.scalars(select(Group).where(Group.teacher_id == t.id))]
        lessons = db.scalar(select(func.count()).select_from(
            select(LessonReport.group_id, LessonReport.day).where(LessonReport.teacher_id == t.id, LessonReport.day >= first, LessonReport.day < nxt).distinct().subquery()
        )) or 0
        att_days = db.scalar(select(func.count()).select_from(
            select(Attendance.group_id, Attendance.day).where(Attendance.group_id.in_(gids), Attendance.day >= first, Attendance.day < nxt, Attendance.marked_by == t.id).distinct().subquery()
        )) or 0 if gids else 0
        tasks = db.scalar(select(func.count(Task.id)).where(Task.created_by == t.id, func.date(Task.created_at) >= first, func.date(Task.created_at) < nxt)) or 0
        anns = db.scalar(select(func.count(Announcement.id)).where(Announcement.created_by == t.id, func.date(Announcement.created_at) >= first, func.date(Announcement.created_at) < nxt)) or 0
        
        plans = list(db.scalars(select(WorkPlan).where(WorkPlan.teacher_id == t.id, WorkPlan.status != "cancelled")))
        plans_done = sum(1 for p in plans if p.status == "done")
        
        # Avg attendance percent
        if gids:
            att_present = db.scalar(select(func.count(Attendance.id)).where(Attendance.group_id.in_(gids), Attendance.day >= first, Attendance.day < nxt, Attendance.status == "present")) or 0
            att_total = db.scalar(select(func.count(Attendance.id)).where(Attendance.group_id.in_(gids), Attendance.day >= first, Attendance.day < nxt)) or 0
            att_pct = round(100 * att_present / att_total) if att_total else 0
        else:
            att_pct = 0

        rows.append({
            "teacher": t.full_name,
            "groups": len(gids),
            "lessons": lessons,
            "attendance_days": att_days,
            "tasks": tasks,
            "announcements": anns,
            "avg_attendance": att_pct,
            "plans_done": plans_done,
            "plans_total": len(plans),
        })

    if format == "csv":
        header = ["Oʻqituvchi", "Guruhlar", "Darslar", "Davomat kunlari", "Topshiriqlar", "Eʼlonlar", "Oʻrtacha davomat %", "Reja (bajarildi/jami)"]
        out = [[r["teacher"], r["groups"], r["lessons"], r["attendance_days"], r["tasks"], r["announcements"], r["avg_attendance"], f'{r["plans_done"]}/{r["plans_total"]}'] for r in rows]
        return _csv_response(out, f"oqituvchilar-{m}.csv", header)

    return {"month": m, "rows": rows}


# ---------------- Students progress report ----------------

@router.get("/students-progress")
def report_students_progress(
    month: Optional[str] = None,
    group_id: Optional[int] = None,
    level: Optional[str] = None,
    format: Literal["json", "csv"] = "json",
    db: Session = Depends(get_db),
):
    m = month or month_of(today_uz())
    first, nxt = month_bounds(m)
    risk_att_pct = int(get_setting(db, "risk_attendance_percent", "60"))
    risk_inact_days = int(get_setting(db, "risk_inactive_days", "14"))
    today = today_uz()

    stmt = select(User).where(User.is_student.is_(True), User.active.is_(True)).order_by(User.full_name)
    if group_id:
        stmt = stmt.where(User.group_id == group_id)
    if level:
        stmt = stmt.where(User.level == level)

    students = list(db.scalars(stmt))
    groups = {g.id: g for g in db.scalars(select(Group))}
    rows = []

    for s in students:
        pts_month = db.scalar(select(func.coalesce(func.sum(PointsLedger.points), 0)).where(PointsLedger.student_id == s.id, func.date(PointsLedger.created_at) >= first, func.date(PointsLedger.created_at) < nxt)) or 0
        pts_total = db.scalar(select(func.coalesce(func.sum(PointsLedger.points), 0)).where(PointsLedger.student_id == s.id)) or 0
        
        att_present = db.scalar(select(func.count(Attendance.id)).where(Attendance.student_id == s.id, Attendance.day >= first, Attendance.day < nxt, Attendance.status == "present")) or 0
        att_total = db.scalar(select(func.count(Attendance.id)).where(Attendance.student_id == s.id, Attendance.day >= first, Attendance.day < nxt)) or 0
        att_pct = round(100 * att_present / att_total) if att_total else 0
        
        subs = db.scalar(select(func.count(Submission.id)).where(Submission.student_id == s.id, func.date(Submission.created_at) >= first, func.date(Submission.created_at) < nxt)) or 0
        
        last_sub = db.scalar(select(func.max(Submission.created_at)).where(Submission.student_id == s.id))
        last_att = db.scalar(select(func.max(Attendance.day)).where(Attendance.student_id == s.id))
        last_led = db.scalar(select(func.max(PointsLedger.created_at)).where(PointsLedger.student_id == s.id))
        
        dates = [d for d in [last_sub, last_att, last_led] if d is not None]
        last_act = max(dates).date() if dates else None
        
        at_risk = False
        if att_total >= 4 and att_pct < risk_att_pct:
            at_risk = True
        elif not last_act or (today - last_act).days >= risk_inact_days:
            last_act = last_act or s.created_at.date()
            if (today - last_act).days >= risk_inact_days:
                at_risk = True
                
        g = groups.get(s.group_id)
        rows.append({
            "id": s.id, "student": s.full_name, "group": g.name if g else "",
            "points_month": int(pts_month), "points_total": int(pts_total),
            "attendance_percent": att_pct, "submissions": subs,
            "last_activity": last_act.isoformat() if last_act else None,
            "at_risk": at_risk,
        })

    if format == "csv":
        header = ["ID", "Oʻquvchi", "Guruh", "Oylik ball", "Jami ball", "Davomat %", "Topshiriqlar", "Oxirgi faollik", "Xavf"]
        out = [[r["id"], r["student"], r["group"], r["points_month"], r["points_total"], r["attendance_percent"], r["submissions"], r["last_activity"] or "", "Ha" if r["at_risk"] else "Yoʻq"] for r in rows]
        return _csv_response(out, f"progress-{m}.csv", header)

    return {"month": m, "rows": rows}


# ---------------- Debtors report ----------------

@router.get("/debtors")
def report_debtors(
    upto: Optional[str] = None,
    format: Literal["json", "csv"] = "json",
    db: Session = Depends(get_db),
):
    m = upto or month_of(today_uz())
    if len(m) != 7:
        raise HTTPException(400, "Oy formati: YYYY-MM")

    today = today_uz()
    cfg = load_pay_settings(db)
    grace = cfg["grace_days"]
    groups = {g.id: g for g in db.scalars(select(Group))}
    invoices = {inv.student_id: inv for inv in db.scalars(select(Invoice).where(Invoice.month == m))}
    paid_map = dict(db.execute(select(Payment.student_id, func.sum(Payment.amount)).where(Payment.month == m, Payment.voided.is_(False)).group_by(Payment.student_id)).all())

    rows = []
    for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True)).order_by(User.full_name)):
        inv = invoices.get(s.id)
        if inv:
            fee = 0 if inv.waived else max(0, inv.amount_due - inv.discount)
            due_day = inv.due_day if inv.due_day else s.fee_day
        else:
            fee = effective_fee(s, groups)
            due_day = s.fee_day
            
        p = int(paid_map.get(s.id, 0))
        if fee <= 0:
            continue
            
        left = max(0, fee - p)
        if left > 0:
            st = pay_status(fee, p, m, due_day, today, grace)
            g = groups.get(s.group_id)
            rows.append({
                "student_id": s.id, "student": s.full_name, "parent_phone": s.parent_phone or "", "phone": s.phone or "",
                "group": g.name if g else "", "fee": fee, "paid": p, "left": left, "status": st,
            })

    if format == "csv":
        header = ["ID", "Oʻquvchi", "Guruh", "Narx", "Toʻlangan", "Qoldiq", "Holat", "Telefon", "Ota-ona tel"]
        out = [[r["student_id"], r["student"], r["group"], r["fee"], r["paid"], r["left"], r["status"], r["phone"], r["parent_phone"]] for r in rows]
        return _csv_response(out, f"qarzdorlar-{m}.csv", header)

    return {"month": m, "rows": rows}
