"""Oʻqituvchi: guruhlar, davomat, topshiriq/xabar berish, dars hisoboti. Oflayn navbat bilan ishlaydi."""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..attendance_service import (
    apply_marks, is_substitute_today,
)
from ..db import get_db
from ..deps import require_teacher
from ..finance import today_uz
from ..models import (Announcement, Attendance, ClientAction, Group, GroupSubstitution, LessonException,
                      LessonReport, PointsLedger, Task, User, WorkPlan, now)
from .content import get_setting

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
STATUS = r"^(present|absent|excused)$"


def my_groups(db: Session, u: User):
    """Own active groups + groups where u is active substitute today."""
    own = list(db.scalars(select(Group).where(Group.teacher_id == u.id, Group.active.is_(True)).order_by(Group.name)))
    own_ids = {g.id for g in own}
    today = today_uz()
    sub_ids = [s.group_id for s in db.scalars(select(GroupSubstitution).where(
        GroupSubstitution.teacher_id == u.id,
        GroupSubstitution.from_day <= today,
        GroupSubstitution.to_day >= today,
    )) if s.group_id not in own_ids]
    subs = list(db.scalars(select(Group).where(Group.id.in_(sub_ids), Group.active.is_(True)).order_by(Group.name))) if sub_ids else []
    return own, subs


def _find_own_or_substitute(db: Session, u: User, gid: int):
    g = db.get(Group, gid)
    if not g or not g.active:
        return None
    if g.teacher_id == u.id:
        return g
    today = today_uz()
    if is_substitute_today(db, g, u.id, today):
        return g
    return None


def _find_own_or_substitute_on(db: Session, u: User, gid: int, day: date):
    g = db.get(Group, gid)
    if not g or not g.active:
        return None
    if g.teacher_id == u.id:
        return g
    if is_substitute_today(db, g, u.id, day):
        return g
    return None


@router.get("/pull")
def pull(u: User = Depends(require_teacher), db: Session = Depends(get_db)):
    own, subs = my_groups(db, u)
    own_ids = {g.id for g in own}
    all_groups = own + subs
    ids = [g.id for g in all_groups]

    studs = {}
    if ids:
        for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True), User.group_id.in_(ids)).order_by(User.full_name)):
            studs.setdefault(s.group_id, []).append({"id": s.id, "full_name": s.full_name, "login": s.login})

    att = {}
    if ids:
        since = now().date() - timedelta(days=14)
        for a in db.scalars(select(Attendance).where(Attendance.group_id.in_(ids), Attendance.day >= since)):
            att.setdefault(f"{a.group_id}|{a.day.isoformat()}", {})[str(a.student_id)] = a.status

    gname = {g.id: g.name for g in all_groups}
    tasks = [{"id": t.id, "title": t.title, "kind": t.kind, "points": t.points, "group_id": t.group_id,
              "group_name": gname.get(t.group_id, ""), "due_date": t.due_date.isoformat() if t.due_date else None, "active": t.active}
             for t in db.scalars(select(Task).where(Task.created_by == u.id).order_by(Task.id.desc()).limit(50))]
    reports = [{"id": r.id, "group_name": gname.get(r.group_id, ""), "day": r.day.isoformat(), "topic": r.topic, "notes": r.notes}
               for r in db.scalars(select(LessonReport).where(LessonReport.teacher_id == u.id).order_by(LessonReport.id.desc()).limit(20))]
    anns = [{"id": a.id, "title": a.title, "body": a.body, "group_name": gname.get(a.group_id, ""), "active": a.active}
            for a in db.scalars(select(Announcement).where(Announcement.created_by == u.id).order_by(Announcement.id.desc()).limit(20))]
    plans = [{"id": p.id, "title": p.title, "due_date": p.due_date.isoformat() if p.due_date else None, "status": p.status}
             for p in db.scalars(select(WorkPlan).where(WorkPlan.teacher_id == u.id, WorkPlan.status != "cancelled").order_by(WorkPlan.id.desc()).limit(50))]

    groups_out = []
    for g in all_groups:
        groups_out.append({
            "id": g.id, "name": g.name, "course": g.course, "level": g.level, "days": g.days,
            "lesson_time": g.lesson_time, "students": studs.get(g.id, []),
            "substitute": g.id not in own_ids,
        })

    return {
        "server_time": now().isoformat(), "today": today_uz().isoformat(),
        "me": {"id": u.id, "full_name": u.full_name, "login": u.login, "is_manager": u.is_manager},
        "groups": groups_out,
        "attendance": att, "tasks": tasks, "reports": reports, "announcements": anns, "plans": plans,
    }


class Rec(BaseModel):
    student_id: int
    status: str = Field(pattern=STATUS)


class AttendanceData(BaseModel):
    group_id: int
    date: date
    records: List[Rec] = Field(max_length=200)


class ReportData(BaseModel):
    group_id: int
    date: date
    topic: str = Field(min_length=2, max_length=160)
    notes: str = Field(default="", max_length=2000)


class TaskData(BaseModel):
    group_id: int
    title: str = Field(min_length=2, max_length=160)
    kind: str = Field(default="daily", pattern=r"^(daily|weekly|monthly|material)$")
    points: int = Field(default=0, ge=0, le=100)
    due_date: Optional[date] = None
    body: str = Field(default="", max_length=8000)


class TaskActiveData(BaseModel):
    task_id: int
    active: bool


class PlanDoneData(BaseModel):
    plan_id: int
    done: bool


class AnnData(BaseModel):
    group_id: int
    title: str = Field(min_length=2, max_length=160)
    body: str = Field(default="", max_length=2000)


class TAction(BaseModel):
    uid: str = Field(min_length=8, max_length=60)
    type: str = Field(max_length=20)
    data: dict


class PushIn(BaseModel):
    actions: List[TAction] = Field(max_length=100)


def _do(db: Session, u: User, a: TAction):
    t = a.type
    if t == "attendance":
        d = AttendanceData(**a.data)
        g = _find_own_or_substitute_on(db, u, d.group_id, d.date)
        if not g:
            raise ValueError("Bu guruh sizga biriktirilmagan")
        today = today_uz()
        window = int(get_setting(db, "teacher_attendance_window_days", "30"))
        if d.date > today + timedelta(days=1) or d.date < today - timedelta(days=window):
            raise ValueError(f"Sana yaroqsiz (kelajak yoki {window} kundan eski)")
        hol = db.scalar(select(LessonException.id).where(
            LessonException.day == d.date,
            LessonException.kind.in_(["holiday", "cancelled"]),
            or_(LessonException.group_id == g.id, LessonException.group_id.is_(None)),
        ))
        if hol:
            raise ValueError("Bu kun dam olish kuni sifatida belgilangan")
        apply_marks(db, u, g, d.date, d.records, source="teacher", client_uid=a.uid)
    elif t == "report":
        d = ReportData(**a.data)
        if not _find_own_or_substitute_on(db, u, d.group_id, d.date):
            raise ValueError("Bu guruh sizga biriktirilmagan")
        db.add(LessonReport(group_id=d.group_id, teacher_id=u.id, day=d.date, topic=d.topic.strip(), notes=d.notes.strip()))
    elif t == "task":
        d = TaskData(**a.data)
        g = _find_own_or_substitute(db, u, d.group_id)
        if not g:
            raise ValueError("Bu guruh sizga biriktirilmagan")
        db.add(Task(title=d.title.strip(), body=d.body, kind=d.kind, level="", group_id=g.id, points=d.points, due_date=d.due_date, created_by=u.id))
    elif t == "task_active":
        d = TaskActiveData(**a.data)
        task = db.get(Task, d.task_id)
        if not task or task.created_by != u.id:
            raise ValueError("Topshiriq sizniki emas")
        task.active = d.active
    elif t == "plan_done":
        d = PlanDoneData(**a.data)
        plan = db.get(WorkPlan, d.plan_id)
        if not plan or plan.teacher_id != u.id or plan.status == "cancelled":
            raise ValueError("Reja sizniki emas")
        plan.status = "done" if d.done else "todo"
        plan.done_at = now() if d.done else None
    elif t == "announcement":
        d = AnnData(**a.data)
        if not _find_own_or_substitute(db, u, d.group_id):
            raise ValueError("Bu guruh sizga biriktirilmagan")
        db.add(Announcement(title=d.title.strip(), body=d.body, group_id=d.group_id, created_by=u.id))
    else:
        raise ValueError("Nomaʼlum harakat")


@router.post("/push")
def push(body: PushIn, u: User = Depends(require_teacher), db: Session = Depends(get_db)):
    results = []
    for a in body.actions:
        if db.get(ClientAction, a.uid):
            results.append({"uid": a.uid, "status": "duplicate"})
            continue
        try:
            _do(db, u, a)
            db.add(ClientAction(uid=a.uid, user_id=u.id))
            db.commit()
            results.append({"uid": a.uid, "status": "ok"})
        except (ValueError, ValidationError) as e:
            db.rollback()
            msg = str(e) if isinstance(e, ValueError) else "Maʼlumot notoʻgʻri"
            results.append({"uid": a.uid, "status": "rejected", "error": msg})
    return {"results": results}
