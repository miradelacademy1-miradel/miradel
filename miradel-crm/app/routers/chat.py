"""Chat: guruh chati + oʻquvchi–oʻqituvchi (shaxsiy). Polling bilan ishlaydi (WebSocket kerak emas).
Admin faqat nazorat qiladi: oʻqiydi va nomaqbul xabarni oʻchiradi."""
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_admin
from ..models import ChatMessage, ChatRead, ChatThread, Group, User
from .admin import audit

router = APIRouter(prefix="/api/chat", tags=["chat"])
admin_router = APIRouter(prefix="/api/admin/chat", tags=["chat-admin"], dependencies=[Depends(require_admin)])
DELETED = "Xabar oʻchirilgan"

_SENT: dict = {}


def _rate_ok(uid: int, limit: int = 30, window: int = 60) -> bool:
    t = time.time()
    arr = [x for x in _SENT.get(uid, []) if t - x < window]
    if len(arr) >= limit:
        _SENT[uid] = arr
        return False
    arr.append(t)
    _SENT[uid] = arr
    return True


def _teacher_of(db: Session, student: User) -> Optional[int]:
    g = db.get(Group, student.group_id) if student.group_id else None
    return g.teacher_id if g and g.active else None


def _accessible(db: Session, u: User) -> list:
    """[(key, kind, group, student, teacher_id)] — foydalanuvchi kira oladigan suhbatlar."""
    out = []
    if u.is_student and u.group_id:
        g = db.get(Group, u.group_id)
        if g and g.active:
            out.append((f"g:{g.id}", "group", g, None, g.teacher_id))
            if g.teacher_id:
                out.append((f"d:{u.id}:{g.teacher_id}", "direct", g, u, g.teacher_id))
    elif u.is_teacher:
        groups = list(db.scalars(select(Group).where(Group.teacher_id == u.id, Group.active.is_(True)).order_by(Group.name)))
        for g in groups:
            out.append((f"g:{g.id}", "group", g, None, u.id))
        gm = {g.id: g for g in groups}
        if gm:
            for s in db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True), User.group_id.in_(list(gm))).order_by(User.full_name)):
                out.append((f"d:{s.id}:{u.id}", "direct", gm[s.group_id], s, u.id))
    return out


def _find(db: Session, u: User, key: str):
    """Foydalanuvchi uchun 'g:<id>' yoki 'd:<oʻquvchi id>' kalitini haqiqiy suhbatga aylantiradi."""
    for k, kind, g, s, tid in _accessible(db, u):
        if k == key or (kind == "direct" and key == f"d:{s.id}"):
            return k, kind, g, s, tid
    raise HTTPException(404, "Suhbat topilmadi")


def _thread(db: Session, k: str, kind: str, g: Group, s: Optional[User], tid: Optional[int]) -> ChatThread:
    t = db.scalar(select(ChatThread).where(ChatThread.key == k))
    if not t:
        t = ChatThread(key=k, kind=kind, group_id=g.id if kind == "group" else None, student_id=s.id if s else None, teacher_id=tid if kind == "direct" else None)
        db.add(t)
        db.flush()
    return t


def _msg_out(m: ChatMessage, names: dict, roles: dict) -> dict:
    return {"id": m.id, "sender_id": m.sender_id, "sender_name": names.get(m.sender_id, ""), "sender_role": roles.get(m.sender_id, "student"),
            "body": DELETED if m.deleted else m.body, "deleted": m.deleted, "at": m.created_at.isoformat()}


def _people(db: Session, ids) -> tuple:
    names, roles = {}, {}
    if ids:
        for x in db.scalars(select(User).where(User.id.in_(list(ids)))):
            names[x.id] = x.full_name
            roles[x.id] = "teacher" if (x.is_teacher or x.is_admin) and not x.is_student else "student"
    return names, roles


def _unread_map(db: Session, u: User, thread_ids: list) -> dict:
    if not thread_ids:
        return {}
    rows = db.execute(
        select(ChatMessage.thread_id, func.count(ChatMessage.id))
        .select_from(ChatMessage).outerjoin(ChatRead, (ChatRead.thread_id == ChatMessage.thread_id) & (ChatRead.user_id == u.id))
        .where(ChatMessage.thread_id.in_(thread_ids), ChatMessage.sender_id != u.id, ChatMessage.deleted.is_(False),
               ChatMessage.id > func.coalesce(ChatRead.last_read_id, 0))
        .group_by(ChatMessage.thread_id)).all()
    return {r[0]: r[1] for r in rows}


@router.get("/threads")
def threads(u: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = _accessible(db, u)
    keys = [a[0] for a in acc]
    tmap = {t.key: t for t in db.scalars(select(ChatThread).where(ChatThread.key.in_(keys)))} if keys else {}
    ids = [t.id for t in tmap.values()]
    last = {}
    if ids:
        sub = select(func.max(ChatMessage.id)).where(ChatMessage.thread_id.in_(ids)).group_by(ChatMessage.thread_id)
        for m in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(sub))):
            last[m.thread_id] = m
    unread = _unread_map(db, u, ids)
    tnames = {x.id: x.full_name for x in db.scalars(select(User).where(User.id.in_([a[4] for a in acc if a[4]])))} if acc else {}
    out = []
    for k, kind, g, s, tid in acc:
        t = tmap.get(k)
        lm = last.get(t.id) if t else None
        if kind == "group":
            title, sub_t, ckey = f"{g.name} guruhi", "Guruh chati", k
        elif u.is_student:
            title, sub_t, ckey = tnames.get(tid, "Oʻqituvchi"), "Oʻqituvchi", f"d:{s.id}"
        else:
            title, sub_t, ckey = s.full_name, g.name, f"d:{s.id}"
        out.append({"key": ckey, "kind": kind, "title": title, "subtitle": sub_t,
                    "last": (DELETED if lm.deleted else lm.body[:80]) if lm else "", "last_at": lm.created_at.isoformat() if lm else None,
                    "unread": unread.get(t.id, 0) if t else 0})
    out.sort(key=lambda x: (x["last_at"] is None, "" if x["last_at"] is None else "", -(0)))  # barqaror boshlangʻich tartib
    out.sort(key=lambda x: x["last_at"] or "", reverse=True)
    return out


@router.get("/unread")
def unread(u: User = Depends(current_user), db: Session = Depends(get_db)):
    keys = [a[0] for a in _accessible(db, u)]
    ids = [t.id for t in db.scalars(select(ChatThread).where(ChatThread.key.in_(keys)))] if keys else []
    return {"count": sum(_unread_map(db, u, ids).values())}


@router.get("/messages")
def messages(key: str, after_id: int = 0, before_id: int = 0, limit: int = 60, u: User = Depends(current_user), db: Session = Depends(get_db)):
    k, kind, g, s, tid = _find(db, u, key)
    t = db.scalar(select(ChatThread).where(ChatThread.key == k))
    if not t:
        return {"messages": [], "last_id": 0}
    limit = max(1, min(limit, 100))
    stmt = select(ChatMessage).where(ChatMessage.thread_id == t.id)
    if after_id:
        rows = list(db.scalars(stmt.where(ChatMessage.id > after_id).order_by(ChatMessage.id).limit(limit)))
    else:
        if before_id:
            stmt = stmt.where(ChatMessage.id < before_id)
        rows = list(reversed(list(db.scalars(stmt.order_by(ChatMessage.id.desc()).limit(limit)))))
    names, roles = _people(db, {m.sender_id for m in rows})
    top = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.thread_id == t.id)) or 0
    if not before_id:
        rd = db.scalar(select(ChatRead).where(ChatRead.thread_id == t.id, ChatRead.user_id == u.id))
        if not rd:
            db.add(ChatRead(thread_id=t.id, user_id=u.id, last_read_id=top))
        elif rd.last_read_id < top:
            rd.last_read_id = top
        db.commit()
    return {"messages": [_msg_out(m, names, roles) for m in rows], "last_id": top}


class SendIn(BaseModel):
    key: str = Field(min_length=3, max_length=40)
    body: str = Field(min_length=1, max_length=1000)
    uid: str = Field(min_length=8, max_length=60)


@router.post("/send")
def send(body: SendIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    k, kind, g, s, tid = _find(db, u, body.key)
    if not _rate_ok(u.id):
        raise HTTPException(429, "Juda tez yozyapsiz, biroz kuting")
    text = body.body.strip()
    if not text:
        raise HTTPException(400, "Xabar boʻsh")
    t = _thread(db, k, kind, g, s, tid)
    dup = db.scalar(select(ChatMessage).where(ChatMessage.thread_id == t.id, ChatMessage.sender_id == u.id, ChatMessage.client_uid == body.uid))
    if dup:
        names, roles = _people(db, {u.id})
        return {"message": _msg_out(dup, names, roles), "status": "duplicate"}
    m = ChatMessage(thread_id=t.id, sender_id=u.id, body=text, client_uid=body.uid)
    db.add(m)
    db.commit()
    names, roles = _people(db, {u.id})
    return {"message": _msg_out(m, names, roles), "status": "ok"}


# ---------- Admin nazorati ----------
@admin_router.get("/threads")
def admin_threads(limit: int = 100, db: Session = Depends(get_db)):
    gm = {g.id: g.name for g in db.scalars(select(Group))}
    um = {x.id: x.full_name for x in db.scalars(select(User))}
    cnt = dict(db.execute(select(ChatMessage.thread_id, func.count(ChatMessage.id)).group_by(ChatMessage.thread_id)).all())
    lastat = dict(db.execute(select(ChatMessage.thread_id, func.max(ChatMessage.created_at)).group_by(ChatMessage.thread_id)).all())
    out = []
    for t in db.scalars(select(ChatThread)):
        title = f"{gm.get(t.group_id, '?')} guruhi" if t.kind == "group" else f"{um.get(t.student_id, '?')} ↔ {um.get(t.teacher_id, '?')}"
        la = lastat.get(t.id)
        out.append({"id": t.id, "kind": t.kind, "title": title, "count": cnt.get(t.id, 0), "last_at": la.isoformat() if la else None})
    out.sort(key=lambda x: x["last_at"] or "", reverse=True)
    return out[:min(limit, 300)]


@admin_router.get("/messages")
def admin_messages(thread_id: int, limit: int = 100, db: Session = Depends(get_db)):
    rows = list(reversed(list(db.scalars(select(ChatMessage).where(ChatMessage.thread_id == thread_id).order_by(ChatMessage.id.desc()).limit(min(limit, 200))))))
    names, roles = _people(db, {m.sender_id for m in rows})
    return [{**_msg_out(m, names, roles), "raw": m.body} for m in rows]


@admin_router.post("/messages/{mid}/delete")
def admin_delete(mid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.get(ChatMessage, mid)
    if not m:
        raise HTTPException(404, "Topilmadi")
    m.deleted = True
    audit(db, admin, "chat.delete", f"msg:{m.id}", f"thread:{m.thread_id} sender:{m.sender_id}")
    db.commit()
    return {"ok": True}
