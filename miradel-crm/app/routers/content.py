"""Admin: topshiriqlar, eʼlonlar, artifaktlar, sozlamalar."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Announcement, Artifact, Group, Setting, Task, User
from .admin import audit

router = APIRouter(prefix="/api/admin", tags=["content"], dependencies=[Depends(require_admin)])
KIND = r"^(daily|weekly|monthly|artifact|material)$"


def get_setting(db: Session, key: str, default: str) -> str:
    s = db.get(Setting, key)
    return s.value if s else default


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    body: str = Field(default="", max_length=8000)
    kind: str = Field(default="daily", pattern=KIND)
    level: str = Field(default="", max_length=60)
    group_id: Optional[int] = None
    points: int = Field(default=0, ge=0, le=1000)
    due_date: Optional[date] = None
    artifact_id: Optional[int] = None


class TaskPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=160)
    body: Optional[str] = Field(default=None, max_length=8000)
    kind: Optional[str] = Field(default=None, pattern=KIND)
    level: Optional[str] = Field(default=None, max_length=60)
    group_id: Optional[int] = None
    points: Optional[int] = Field(default=None, ge=0, le=1000)
    due_date: Optional[date] = None
    artifact_id: Optional[int] = None
    active: Optional[bool] = None


def task_out(t: Task, gm: dict) -> dict:
    return {"id": t.id, "title": t.title, "body": t.body, "kind": t.kind, "level": t.level, "group_id": t.group_id,
            "group_name": gm.get(t.group_id, ""), "points": t.points, "due_date": t.due_date.isoformat() if t.due_date else None,
            "artifact_id": t.artifact_id, "active": t.active}


def _check_refs(db: Session, group_id, artifact_id):
    if group_id and not db.get(Group, group_id):
        raise HTTPException(400, "Guruh topilmadi")
    if artifact_id and not db.get(Artifact, artifact_id):
        raise HTTPException(400, "Artifakt topilmadi")


@router.get("/tasks")
def tasks(db: Session = Depends(get_db)):
    gm = {g.id: g.name for g in db.scalars(select(Group))}
    return [task_out(t, gm) for t in db.scalars(select(Task).order_by(Task.id.desc()).limit(300))]


@router.post("/tasks")
def create_task(body: TaskIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_refs(db, body.group_id, body.artifact_id)
    t = Task(**body.model_dump(), created_by=admin.id)
    t.title = t.title.strip()
    db.add(t)
    audit(db, admin, "task.create", t.title)
    db.commit()
    return task_out(t, {})


@router.patch("/tasks/{tid}")
def patch_task(tid: int, body: TaskPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404, "Topilmadi")
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, data.get("group_id"), data.get("artifact_id"))
    for k, v in data.items():
        setattr(t, k, v)
    audit(db, admin, "task.update", t.title, ",".join(data.keys()))
    db.commit()
    return task_out(t, {})


class AnnIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    body: str = Field(default="", max_length=2000)
    group_id: Optional[int] = None


class AnnPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=160)
    body: Optional[str] = Field(default=None, max_length=2000)
    active: Optional[bool] = None


def ann_out(a: Announcement, gm: dict) -> dict:
    return {"id": a.id, "title": a.title, "body": a.body, "group_id": a.group_id,
            "group_name": gm.get(a.group_id, ""), "active": a.active}


@router.get("/announcements")
def announcements(db: Session = Depends(get_db)):
    gm = {g.id: g.name for g in db.scalars(select(Group))}
    return [ann_out(a, gm) for a in db.scalars(select(Announcement).order_by(Announcement.id.desc()).limit(100))]


@router.post("/announcements")
def create_ann(body: AnnIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    _check_refs(db, body.group_id, None)
    a = Announcement(**body.model_dump())
    db.add(a)
    audit(db, admin, "announcement.create", body.title)
    db.commit()
    return ann_out(a, {})


@router.patch("/announcements/{aid}")
def patch_ann(aid: int, body: AnnPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(Announcement, aid)
    if not a:
        raise HTTPException(404, "Topilmadi")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    audit(db, admin, "announcement.update", a.title)
    db.commit()
    return ann_out(a, {})


class ArtIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    icon: str = Field(default="🏺", max_length=16)
    description: str = Field(default="", max_length=200)


class ArtPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    icon: Optional[str] = Field(default=None, max_length=16)
    description: Optional[str] = Field(default=None, max_length=200)
    active: Optional[bool] = None


def art_out(a: Artifact) -> dict:
    return {"id": a.id, "name": a.name, "icon": a.icon, "description": a.description, "active": a.active}


@router.get("/artifacts")
def artifacts(db: Session = Depends(get_db)):
    return [art_out(a) for a in db.scalars(select(Artifact).order_by(Artifact.id))]


@router.post("/artifacts")
def create_art(body: ArtIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = Artifact(**body.model_dump())
    db.add(a)
    audit(db, admin, "artifact.create", body.name)
    db.commit()
    return art_out(a)


@router.patch("/artifacts/{aid}")
def patch_art(aid: int, body: ArtPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(Artifact, aid)
    if not a:
        raise HTTPException(404, "Topilmadi")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    audit(db, admin, "artifact.update", a.name)
    db.commit()
    return art_out(a)


class SettingsIn(BaseModel):
    activity_target: int = Field(ge=10, le=100000)
    attendance_points: Optional[int] = Field(default=None, ge=0, le=50)
    attendance_points_mode: Optional[str] = Field(default=None, pattern=r"^(all|scheduled_only)$")
    teacher_attendance_window_days: Optional[int] = Field(default=None, ge=1, le=365)
    streak_alert_days: Optional[int] = Field(default=None, ge=1, le=30)
    risk_attendance_percent: Optional[int] = Field(default=None, ge=0, le=100)
    risk_inactive_days: Optional[int] = Field(default=None, ge=1, le=365)


def _settings(db: Session) -> dict:
    return {
        "activity_target": int(get_setting(db, "activity_target", "300")),
        "attendance_points": int(get_setting(db, "attendance_points", "2")),
        "attendance_points_mode": get_setting(db, "attendance_points_mode", "all"),
        "teacher_attendance_window_days": int(get_setting(db, "teacher_attendance_window_days", "30")),
        "streak_alert_days": int(get_setting(db, "streak_alert_days", "3")),
        "risk_attendance_percent": int(get_setting(db, "risk_attendance_percent", "60")),
        "risk_inactive_days": int(get_setting(db, "risk_inactive_days", "14")),
    }


@router.get("/settings")
def settings(db: Session = Depends(get_db)):
    return _settings(db)


@router.put("/settings")
def put_settings(body: SettingsIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    for key, val in (
        ("activity_target", body.activity_target),
        ("attendance_points", body.attendance_points),
        ("attendance_points_mode", body.attendance_points_mode),
        ("teacher_attendance_window_days", body.teacher_attendance_window_days),
        ("streak_alert_days", body.streak_alert_days),
        ("risk_attendance_percent", body.risk_attendance_percent),
        ("risk_inactive_days", body.risk_inactive_days),
    ):
        if val is None:
            continue
        s = db.get(Setting, key) or Setting(key=key)
        s.value = str(val)
        db.add(s)
    audit(db, admin, "settings.update", "settings")
    db.commit()
    return _settings(db)
