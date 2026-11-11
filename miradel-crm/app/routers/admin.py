import re
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin, user_out
from ..models import AuditLog, Group, User
from ..security import gen_password, hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
LOGIN_RE = re.compile(r"^[a-z0-9._-]{3,30}$")


def audit(db: Session, actor: User, action: str, target: str = "", detail: str = ""):
    db.add(AuditLog(actor_id=actor.id, action=action, target=target, detail=detail))


def group_out(g: Group, names: dict) -> dict:
    return {"id": g.id, "name": g.name, "course": g.course, "level": g.level, "days": g.days,
            "lesson_time": g.lesson_time, "teacher_id": g.teacher_id, "teacher_name": names.get(g.teacher_id, ""), "active": g.active}


# ---------- Oʻquvchilar ----------
class StudentIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=30)
    group_id: Optional[int] = None
    level: str = Field(default="", max_length=60)


class UserPatch(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    group_id: Optional[int] = None
    level: Optional[str] = Field(default=None, max_length=60)
    active: Optional[bool] = None


@router.get("/students")
def students(q: str = "", group_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(User).where(User.is_student.is_(True)).order_by(User.id.desc())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.login.ilike(like), User.phone.ilike(like)))
    if group_id:
        stmt = stmt.where(User.group_id == group_id)
    gm = {g.id: g.name for g in db.scalars(select(Group))}
    return [{**user_out(u), "group_name": gm.get(u.group_id, "")} for u in db.scalars(stmt)]


@router.post("/students")
def create_student(body: StudentIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.group_id and not db.get(Group, body.group_id):
        raise HTTPException(400, "Guruh topilmadi")
    pwd = gen_password()
    u = User(login="tmp-" + secrets.token_hex(6), password_hash=hash_password(pwd), full_name=body.full_name.strip(),
             phone=body.phone.strip(), is_student=True, group_id=body.group_id, level=body.level.strip())
    db.add(u)
    db.flush()
    u.login = f"miradel-{u.id:04d}"
    audit(db, admin, "student.create", u.login, u.full_name)
    db.commit()
    return {"user": user_out(u), "password": pwd}


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Topilmadi")
    data = body.model_dump(exclude_unset=True)
    if data.get("active") is False and u.id == admin.id:
        raise HTTPException(400, "Oʻzingizni oʻchira olmaysiz")
    if data.get("group_id") and not db.get(Group, data["group_id"]):
        raise HTTPException(400, "Guruh topilmadi")
    for k, v in data.items():
        setattr(u, k, v.strip() if isinstance(v, str) else v)
    if data.get("active") is False:
        u.token_version = (u.token_version or 0) + 1  # qayta yoqilsa ham eski tokenlar ishlamasin
    audit(db, admin, "user.update", u.login, ",".join(data.keys()))
    db.commit()
    return user_out(u)


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Topilmadi")
    pwd = gen_password()
    u.password_hash = hash_password(pwd)
    u.token_version = (u.token_version or 0) + 1  # eski qurilmalardagi kirish bekor qilinadi
    audit(db, admin, "user.reset_password", u.login)
    db.commit()
    return {"user": user_out(u), "password": pwd}


# ---------- Xodimlar ----------
class StaffIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(default="", max_length=30)
    login: Optional[str] = None
    is_teacher: bool = False
    is_manager: bool = False


class RolesIn(BaseModel):
    is_teacher: bool
    is_manager: bool


@router.get("/staff")
def staff(db: Session = Depends(get_db)):
    stmt = select(User).where(or_(User.is_teacher.is_(True), User.is_manager.is_(True), User.is_admin.is_(True))).order_by(User.id)
    return [user_out(u) for u in db.scalars(stmt)]


@router.post("/staff")
def create_staff(body: StaffIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not (body.is_teacher or body.is_manager):
        raise HTTPException(400, "Kamida bitta rol tanlang (oʻqituvchi yoki menejer)")
    custom = body.login.strip().lower() if body.login else None
    if custom:
        if not LOGIN_RE.match(custom):
            raise HTTPException(400, "Login: 3-30 belgi, kichik lotin harf, raqam, nuqta, chiziq")
        if db.scalar(select(User).where(User.login == custom)):
            raise HTTPException(400, "Bu login band")
    pwd = gen_password()
    u = User(login=custom or "tmp-" + secrets.token_hex(6), password_hash=hash_password(pwd),
             full_name=body.full_name.strip(), phone=body.phone.strip(),
             is_teacher=body.is_teacher, is_manager=body.is_manager)
    db.add(u)
    db.flush()
    if not custom:
        u.login = f"xodim-{u.id:03d}"
    audit(db, admin, "staff.create", u.login, u.full_name)
    db.commit()
    return {"user": user_out(u), "password": pwd}


@router.patch("/staff/{uid}/roles")
def set_roles(uid: int, body: RolesIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.is_student:
        raise HTTPException(404, "Xodim topilmadi")
    if not (body.is_teacher or body.is_manager or u.is_admin):
        raise HTTPException(400, "Kamida bitta rol qolishi kerak")
    u.is_teacher, u.is_manager = body.is_teacher, body.is_manager
    audit(db, admin, "staff.roles", u.login, f"teacher={body.is_teacher},manager={body.is_manager}")
    db.commit()
    return user_out(u)


# ---------- Guruhlar ----------
class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    course: str = Field(default="", max_length=80)
    level: str = Field(default="", max_length=60)
    days: str = Field(default="", pattern=r"^[1-7]{0,7}$")
    lesson_time: str = Field(default="", max_length=10)
    teacher_id: Optional[int] = None


class GroupPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    course: Optional[str] = Field(default=None, max_length=80)
    level: Optional[str] = Field(default=None, max_length=60)
    days: Optional[str] = Field(default=None, pattern=r"^[1-7]{0,7}$")
    lesson_time: Optional[str] = Field(default=None, max_length=10)
    teacher_id: Optional[int] = None
    active: Optional[bool] = None


def _check_teacher(db: Session, tid: Optional[int]):
    if tid:
        t = db.get(User, tid)
        if not t or not t.is_teacher:
            raise HTTPException(400, "Oʻqituvchi topilmadi")


@router.get("/groups")
def groups(db: Session = Depends(get_db)):
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.is_teacher.is_(True)))}
    return [group_out(g, names) for g in db.scalars(select(Group).order_by(Group.name))]


@router.post("/groups")
def create_group(body: GroupIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(Group).where(Group.name == body.name.strip())):
        raise HTTPException(400, "Bunday guruh bor")
    _check_teacher(db, body.teacher_id)
    g = Group(name=body.name.strip(), course=body.course.strip(), level=body.level.strip(), days="".join(sorted(set(body.days))),
              lesson_time=body.lesson_time.strip(), teacher_id=body.teacher_id)
    db.add(g)
    audit(db, admin, "group.create", g.name)
    db.commit()
    return group_out(g, {})


@router.patch("/groups/{gid}")
def patch_group(gid: int, body: GroupPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    g = db.get(Group, gid)
    if not g:
        raise HTTPException(404, "Topilmadi")
    data = body.model_dump(exclude_unset=True)
    if "teacher_id" in data:
        _check_teacher(db, data["teacher_id"])
    for k, v in data.items():
        setattr(g, k, v.strip() if isinstance(v, str) else v)
    audit(db, admin, "group.update", g.name, ",".join(data.keys()))
    db.commit()
    return group_out(g, {})


@router.get("/audit")
def audit_list(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 200)))
    return [{"id": r.id, "actor_id": r.actor_id, "action": r.action, "target": r.target,
             "detail": r.detail, "at": r.created_at.isoformat()} for r in rows]
