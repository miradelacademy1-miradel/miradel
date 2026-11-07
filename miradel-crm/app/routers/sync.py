"""Oʻquvchi ilovasi uchun sinxronlash: pull (snapshot) va push (oflayn harakatlar)."""
from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, user_out
from ..finance import clamp_day, effective_fee, month_of, next_month, pay_status, today_uz
from ..models import (Announcement, Artifact, Attendance, Group, Payment, PointsLedger, Submission, Task, User, UserArtifact, now)
from .content import get_setting

router = APIRouter(prefix="/api/sync", tags=["sync"])


def student_only(u: User = Depends(current_user)) -> User:
    if not u.is_student:
        raise HTTPException(403, "Bu boʻlim oʻquvchilar uchun")
    return u


def visible(u: User, t: Task) -> bool:
    if not t.active:
        return False
    if t.group_id:
        return t.group_id == u.group_id
    return (not t.level) or t.level == u.level


def _task_filter(u: User):
    conds = [and_(Task.group_id.is_(None), or_(Task.level == "", Task.level == u.level))]
    if u.group_id:
        conds.append(Task.group_id == u.group_id)
    return or_(*conds)


def _rating(db: Session, group_id=None):
    stmt = (select(User.id, User.full_name, func.coalesce(func.sum(PointsLedger.points), 0).label("p"))
            .select_from(User).outerjoin(PointsLedger, PointsLedger.student_id == User.id)
            .where(User.is_student.is_(True), User.active.is_(True)))
    if group_id:
        stmt = stmt.where(User.group_id == group_id)
    return db.execute(stmt.group_by(User.id, User.full_name).order_by(desc("p"), User.id)).all()


@router.get("/pull")
def pull(u: User = Depends(student_only), db: Session = Depends(get_db)):
    group = db.get(Group, u.group_id) if u.group_id else None
    teacher = db.get(User, group.teacher_id) if group and group.teacher_id else None

    subs = {s.task_id: s for s in db.scalars(select(Submission).where(Submission.student_id == u.id))}
    tasks = [{"id": t.id, "title": t.title, "body": t.body, "kind": t.kind, "points": t.points,
              "due_date": t.due_date.isoformat() if t.due_date else None, "artifact_id": t.artifact_id,
              "done": t.id in subs} for t in db.scalars(select(Task).where(Task.active.is_(True), _task_filter(u)).order_by(Task.id.desc()).limit(300))]

    ann_filter = Announcement.group_id.is_(None) if not u.group_id else or_(Announcement.group_id.is_(None), Announcement.group_id == u.group_id)
    anns = [{"id": a.id, "title": a.title, "body": a.body}
            for a in db.scalars(select(Announcement).where(Announcement.active.is_(True), ann_filter).order_by(Announcement.id.desc()).limit(20))]

    earned = {r for r in db.scalars(select(UserArtifact.artifact_id).where(UserArtifact.student_id == u.id))}
    arts = [{"id": a.id, "name": a.name, "icon": a.icon, "description": a.description, "earned": a.id in earned}
            for a in db.scalars(select(Artifact).where(Artifact.active.is_(True)).order_by(Artifact.id))]

    total = db.scalar(select(func.coalesce(func.sum(PointsLedger.points), 0)).where(PointsLedger.student_id == u.id)) or 0
    month = db.scalar(select(func.coalesce(func.sum(PointsLedger.points), 0)).where(
        PointsLedger.student_id == u.id, PointsLedger.created_at >= now() - timedelta(days=30))) or 0
    target = int(get_setting(db, "activity_target", "300"))

    since = now().date() - timedelta(days=30)
    att = dict(db.execute(select(Attendance.status, func.count()).where(Attendance.student_id == u.id, Attendance.day >= since).group_by(Attendance.status)).all())
    attendance = {"present": att.get("present", 0), "absent": att.get("absent", 0), "excused": att.get("excused", 0)}

    td = today_uz()
    mth = month_of(td)
    fee = effective_fee(u, {group.id: group} if group else {})
    paid_m = int(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.student_id == u.id, Payment.month == mth, Payment.voided.is_(False))) or 0)
    pst = pay_status(fee, paid_m, mth, u.fee_day, td)
    nxt = clamp_day(next_month(mth), u.fee_day) if pst == "paid" else clamp_day(mth, u.fee_day)
    payment = {"month": mth, "fee": fee, "paid": paid_m, "left": max(0, fee - paid_m), "status": pst, "next_date": nxt.isoformat()}

    center = _rating(db)
    grp = _rating(db, u.group_id) if u.group_id else []
    rank_c = next((i + 1 for i, r in enumerate(center) if r.id == u.id), None)
    rank_g = next((i + 1 for i, r in enumerate(grp) if r.id == u.id), None)
    fmt = lambda rows: [{"name": r.full_name, "points": int(r.p), "me": r.id == u.id} for r in rows[:20]]

    return {
        "server_time": now().isoformat(),
        "me": {"id": u.id, "full_name": u.full_name, "login": u.login, "level": u.level},
        "group": ({"id": group.id, "name": group.name, "course": group.course, "level": group.level, "days": group.days,
                   "lesson_time": group.lesson_time, "teacher_name": teacher.full_name if teacher else ""} if group else None),
        "tasks": tasks, "announcements": anns, "artifacts": arts, "attendance": attendance, "payment": payment,
        "stats": {"total": int(total), "month": int(month), "target": target,
                  "activity": min(100, round(month * 100 / target)) if target else 0,
                  "rank_center": rank_c, "rank_group": rank_g, "students": len(center)},
        "rating": {"center": fmt(center), "group": fmt(grp)},
    }


class Action(BaseModel):
    uid: str = Field(min_length=8, max_length=60)
    type: str = Field(max_length=20)
    task_id: int
    answer: str = Field(default="", max_length=1000)


class PushIn(BaseModel):
    actions: List[Action] = Field(max_length=100)


@router.post("/push")
def push(body: PushIn, u: User = Depends(student_only), db: Session = Depends(get_db)):
    results = []
    for a in body.actions:
        if a.type != "complete":
            results.append({"uid": a.uid, "status": "rejected", "error": "Nomaʼlum harakat"})
            continue
        t = db.get(Task, a.task_id)
        if not t or not visible(u, t) or t.kind == "material":
            results.append({"uid": a.uid, "status": "rejected", "error": "Topshiriq mavjud emas"})
            continue
        if db.scalar(select(Submission.id).where(Submission.task_id == t.id, Submission.student_id == u.id)):
            results.append({"uid": a.uid, "status": "duplicate"})
            continue
        db.add(Submission(task_id=t.id, student_id=u.id, answer=a.answer.strip(), points_awarded=t.points, client_uid=a.uid))
        if t.points:
            db.add(PointsLedger(student_id=u.id, source="task", ref_id=t.id, points=t.points, note=t.title[:200]))
        if t.artifact_id and not db.scalar(select(UserArtifact.id).where(UserArtifact.student_id == u.id, UserArtifact.artifact_id == t.artifact_id)):
            db.add(UserArtifact(student_id=u.id, artifact_id=t.artifact_id))
        db.commit()
        results.append({"uid": a.uid, "status": "ok"})
    return {"results": results}
