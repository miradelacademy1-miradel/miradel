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
    return {"id": a.id, "title": a.title, "body": a.body, "group_id":
