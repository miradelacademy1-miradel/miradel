from typing import Optional
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .finance import month_bounds
from .models import Attendance, Group, LessonReport, Payment, SalaryAdjustment, SalaryPayout, User
from .routers.content import get_setting


def get_salary_rows(db: Session, m: str):
    first, nxt = month_bounds(m)
    source = get_setting(db, "salary_lesson_source", "reports")
    
    out = []
    for t in db.scalars(select(User).where(User.is_teacher.is_(True), User.active.is_(True)).order_by(User.full_name)):
        gids = [g.id for g in db.scalars(select(Group).where(Group.teacher_id == t.id))]
        
        lessons = 0
        if source in ("reports", "either"):
            lessons_reports = db.scalar(select(func.count()).select_from(
                select(LessonReport.group_id, LessonReport.day)
                .where(LessonReport.teacher_id == t.id, LessonReport.day >= first, LessonReport.day < nxt)
                .distinct().subquery()
            )) or 0
            lessons += lessons_reports
            
        if source in ("attendance", "either"):
            lessons_att = db.scalar(select(func.count()).select_from(
                select(Attendance.group_id, Attendance.day)
                .where(Attendance.group_id.in_(gids), Attendance.marked_by == t.id, Attendance.day >= first, Attendance.day < nxt)
                .distinct().subquery()
            )) or 0
            if source == "either":
                # Union distinct on (group, day) is complex in SQLAlchemy, do manual merge if needed
                # For simplicity in 'either', we'll just check if attendance adds new days.
                # Actually, a raw union is better.
                all_lessons = db.execute(
                    select(LessonReport.group_id, LessonReport.day).where(LessonReport.teacher_id == t.id, LessonReport.day >= first, LessonReport.day < nxt)
                    .union(
                        select(Attendance.group_id, Attendance.day).where(Attendance.group_id.in_(gids), Attendance.marked_by == t.id, Attendance.day >= first, Attendance.day < nxt)
                    )
                ).all()
                lessons = len(all_lessons)
            else:
                lessons = lessons_att

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
        
        adjustments = int(db.scalar(select(func.coalesce(func.sum(SalaryAdjustment.amount), 0)).where(
            SalaryAdjustment.teacher_id == t.id, SalaryAdjustment.month == m, SalaryAdjustment.voided.is_(False)
        )) or 0)
        
        amount_total = amount + adjustments
        balance = amount - paid
        balance_total = amount_total - paid

        out.append({
            "id": t.id, "full_name": t.full_name, "mode": t.salary_mode, "rate": t.salary_rate, "lessons": lessons,
            "collected": collected, "amount": amount, "paid": paid, "balance": balance,
            "adjustments": adjustments, "amount_total": amount_total, "balance_total": balance_total
        })
    return out


def get_salary_sheet(db: Session, teacher_id: int, m: str):
    first, nxt = month_bounds(m)
    t = db.get(User, teacher_id)
    if not t or not t.is_teacher:
        return None
        
    source = get_setting(db, "salary_lesson_source", "reports")
    gids = [g.id for g in db.scalars(select(Group).where(Group.teacher_id == t.id))]
    gm = {g.id: g.name for g in db.scalars(select(Group).where(Group.id.in_(gids)))} if gids else {}
    
    lessons_list = []
    if source in ("reports", "either"):
        for r in db.scalars(select(LessonReport).where(LessonReport.teacher_id == t.id, LessonReport.day >= first, LessonReport.day < nxt).order_by(LessonReport.day)):
            lessons_list.append({"date": r.day.isoformat(), "group": gm.get(r.group_id, ""), "topic": r.topic, "source": "report"})
            
    if source == "attendance":
        # distinct (group, day)
        atts = db.execute(
            select(Attendance.group_id, Attendance.day)
            .where(Attendance.group_id.in_(gids), Attendance.marked_by == t.id, Attendance.day >= first, Attendance.day < nxt)
            .distinct().order_by(Attendance.day)
        ).all()
        for r in atts:
            lessons_list.append({"date": r.day.isoformat(), "group": gm.get(r.group_id, ""), "topic": "Davomat belgilangan", "source": "attendance"})
            
    if source == "either":
        # Combine unique (group_id, day)
        seen = {(l["date"], l["group"]) for l in lessons_list}
        atts = db.execute(
            select(Attendance.group_id, Attendance.day)
            .where(Attendance.group_id.in_(gids), Attendance.marked_by == t.id, Attendance.day >= first, Attendance.day < nxt)
            .distinct().order_by(Attendance.day)
        ).all()
        for r in atts:
            if (r.day.isoformat(), gm.get(r.group_id, "")) not in seen:
                lessons_list.append({"date": r.day.isoformat(), "group": gm.get(r.group_id, ""), "topic": "Davomat belgilangan", "source": "attendance"})
                seen.add((r.day.isoformat(), gm.get(r.group_id, "")))
        lessons_list.sort(key=lambda x: x["date"])

    # Filters
    collected = 0
    if gids and t.salary_mode == "percent":
        collected = int(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).join(User, User.id == Payment.student_id).where(
            Payment.month == m, Payment.voided.is_(False), User.group_id.in_(gids))) or 0)
            
    if t.salary_mode == "per_lesson":
        amount = len(lessons_list) * t.salary_rate
    elif t.salary_mode == "percent":
        amount = round(collected * t.salary_rate / 100)
    else:
        amount = t.salary_rate

    adjustments = list(db.scalars(select(SalaryAdjustment).where(
        SalaryAdjustment.teacher_id == t.id, SalaryAdjustment.month == m, SalaryAdjustment.voided.is_(False)
    )))
    payouts = list(db.scalars(select(SalaryPayout).where(SalaryPayout.teacher_id == t.id, SalaryPayout.month == m)))
    
    adj_sum = sum(a.amount for a in adjustments)
    paid = sum(p.amount for p in payouts)
    
    return {
        "teacher": t.full_name,
        "month": m,
        "mode": t.salary_mode,
        "rate": t.salary_rate,
        "lessons_list": lessons_list,
        "collected": collected,
        "amount": amount,
        "adjustments": [{"id": a.id, "amount": a.amount, "reason": a.reason, "date": a.created_at.isoformat()} for a in adjustments],
        "adjustments_sum": adj_sum,
        "amount_total": amount + adj_sum,
        "payouts": [{"id": p.id, "amount": p.amount, "note": p.note, "date": p.paid_on.isoformat()} for p in payouts],
        "paid": paid,
        "balance_total": amount + adj_sum - paid,
    }
