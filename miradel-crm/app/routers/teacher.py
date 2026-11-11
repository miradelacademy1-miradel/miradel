"""Oʻqituvchi: guruhlar, davomat, topshiriq/xabar berish, dars hisoboti. Oflayn navbat bilan ishlaydi."""
import logging
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_teacher
from ..finance import today_uz
from ..models import (Announcement, Attendance, ClientAction, Group, LessonReport, PointsLedger, Task, User, WorkPlan, now)
from .content import get_setting

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
log = logging.getLogger("miradel")
STATUS = r"^(present|absent|excused)$"


def my_groups(db: Session, u: User):
    return list(db.scalars(select(Group).where(Group.teacher_id == u.id, Group.active.is_(True)).order_by(Group.name)))


@router.get("/pull")
def pull(u: User = Depends(require_teacher), db: Session = Depends(get_db)):
    groups = my_groups(db, u)
    ids = [g.id for g in groups]
    studs = {}
    if ids:
        for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True), User.group_id.in_(ids)).order_by(User.full_name)):
            studs.setdefault(s.group_id, []).append({"id": s.id, "full_name": s.full_name, "login": s.login})
    att = {}
    if ids:
        since = now().date() - timedelta(days=14)
        for a in db.scalars(select(Attendance).where(Attendance.group_id.in_(ids), Attendance.day >= since)):
            att.setdefault(f"{a.group_id}|{a.day.isoformat()}", {})[str(a.student_id)] = a.status
    gname = {g.id: g.name for g in groups}
    tasks = [{"id": t.id, "title": t.title, "kind": t.kind, "points": t.points, "group_id": t.group_id,
              "group_name": gname.get(t.group_id, ""), "due_date": t.due_date.isoformat() if t.due_date else None, "active": t.active}
             for t in db.scalars(select(Task).where(Task.created_by == u.id).order_by(Task.id.desc()).limit(50))]
    reports = [{"id": r.id, "group_name": gname.get(r.group_id, ""), "day": r.day.isoformat(), "topic": r.topic, "notes": r.notes}
               for r in db.scalars(select(LessonReport).where(LessonReport.teacher_id == u.id).order_by(LessonReport.id.desc()).limit(20))]
    anns = [{"id": a.id, "title": a.title, "body": a.body, "group_name": gname.get(a.group_id, ""), "active": a.active}
            for a in db.scalars(select(Announcement).where(Announcement.created_by == u.id).order_by(Announcement.id.desc()).limit(20))]
    plans = [{"id": p.id, "title": p.title, "due_date": p.due_date.isoformat() if p.due_date else None, "status": p.status}
             for p in db.scalars(select(WorkPlan).where(WorkPlan.teacher_id == u.id, WorkPlan.status != "cancelled").order_by(WorkPlan.id.desc()).limit(50))]
    return {
        "server_time": now().isoformat(), "today": today_uz().isoformat(),
        "me": {"id": u.id, "full_name": u.full_name, "login": u.login, "is_manager": u.is_manager},
        "groups": [{"id": g.id, "name": g.name, "course": g.course, "level": g.level, "days": g.days,
                    "lesson_time": g.lesson_time, "students": studs.get(g.id, [])} for g in groups],
        "attendance": att, "tasks": tasks, "reports": reports, "announcements": anns, "plans": plans,
    }


# ---------- Oflayn navbat ----------
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
    actions: List[TAction] = Field(max_length=500)


def _own_group(db: Session, u: User, gid: int) -> Group:
    g = db.get(Group, gid)
    if not g or g.teacher_id != u.id or not g.active:
        raise ValueError("Bu guruh sizga biriktirilmagan")
    return g


def _do(db: Session, u: User, a: TAction):
    t = a.type
    if t == "attendance":
        d = AttendanceData(**a.data)
        g = _own_group(db, u, d.group_id)
        today = today_uz()
        if d.date > today + timedelta(days=1) or d.date < today - timedelta(days=30):
            raise ValueError("Sana yaroqsiz (kelajak yoki 30 kundan eski)")
        pp = int(get_setting(db, "attendance_points", "2"))
        ok_ids = {s.id for s in db.scalars(select(User).where(User.is_student.is_(True), User.group_id == g.id))}
        for r in d.records:
            if r.student_id not in ok_ids:
                continue
            row = db.scalar(select(Attendance).where(Attendance.group_id == g.id, Attendance.student_id == r.student_id, Attendance.day == d.date))
            if row and row.status == r.status:
                continue
            if row:
                for old in db.scalars(select(PointsLedger).where(PointsLedger.source == "attendance", PointsLedger.ref_id == row.id)):
                    db.delete(old)
                row.status, row.marked_by = r.status, u.id
            else:
                row = Attendance(group_id=g.id, student_id=r.student_id, day=d.date, status=r.status, marked_by=u.id)
                db.add(row)
                db.flush()
            if r.status == "present" and pp:
                db.add(PointsLedger(student_id=r.student_id, source="attendance", ref_id=row.id, points=pp, note=f"Davomat {d.date.isoformat()}"))
    elif t == "report":
        d = ReportData(**a.data)
        _own_group(db, u, d.group_id)
        db.add(LessonReport(group_id=d.group_id, teacher_id=u.id, day=d.date, topic=d.topic.strip(), notes=d.notes.strip()))
    elif t == "task":
        d = TaskData(**a.data)
        g = _own_group(db, u, d.group_id)
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
        _own_group(db, u, d.group_id)
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
        except Exception:  # kutilmagan xato butun navbatni toʻxtatib qoʻymasin
            db.rollback()
            log.exception("teacher.push xatosi (teacher=%s, type=%s)", u.id, a.type)
            results.append({"uid": a.uid, "status": "rejected", "error": "Server xatosi, administratorga xabar bering"})
    return {"results": results}
