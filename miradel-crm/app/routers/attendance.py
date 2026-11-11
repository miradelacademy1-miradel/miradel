"""Manager/admin attendance API: day view, matrix, corrections, follow-ups, calendar."""
import csv
import io
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..attendance_service import (
    apply_marks, effective_teacher_today, expected_days_in_range,
    has_overlapping_substitution, is_expected_day,
)
from ..audit import audit
from ..db import get_db
from ..finance import today_uz
from ..models import (
    AbsenceFollowup, Attendance, AttendanceBatch, Group, GroupSubstitution,
    LessonException, Setting, User,
)
from .manager import finance_user

router = APIRouter(prefix="/api/attendance", tags=["attendance"], dependencies=[Depends(finance_user)])


def _parse_day(s: Optional[str]) -> date:
    if not s:
        return today_uz()
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "Sana formati: YYYY-MM-DD")


def _parse_month(s: Optional[str]) -> str:
    if not s:
        d = today_uz()
        return f"{d.year}-{d.month:02d}"
    if len(s) != 7 or s[4] != "-":
        raise HTTPException(400, "Oy formati: YYYY-MM")
    return s


def _month_bounds(m: str) -> tuple[date, date]:
    y, mo = int(m[:4]), int(m[5:7])
    first = date(y, mo, 1)
    if mo == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, mo + 1, 1)
    return first, nxt - timedelta(days=1)


def _get_setting(db: Session, key: str, default: str) -> str:
    s = db.get(Setting, key)
    return s.value if s else default


def _groups_all(db: Session) -> list[Group]:
    return list(db.scalars(select(Group).order_by(Group.name)))


def _teacher_names(db: Session) -> dict[int, str]:
    return {u.id: u.full_name for u in db.scalars(select(User).where(User.is_teacher.is_(True)))}


def _student_phone(s: User) -> str:
    return getattr(s, "phone", "") or ""


def _student_parent_phone(s: User) -> str:
    return getattr(s, "parent_phone", "") or ""


# -------- 1. Day state --------

def _day_state(db: Session, d: date) -> dict:
    groups = _groups_all(db)
    exceptions = list(db.scalars(select(LessonException).where(LessonException.day == d)))
    teacher_names = _teacher_names(db)

    result = []
    for g in groups:
        if not g.active:
            continue
        weekday = d.isoweekday()
        scheduled = str(weekday) in (g.days or "")
        group_exc = [e for e in exceptions if e.group_id == g.id or e.group_id is None]
        is_holiday = any(e.kind == "holiday" for e in group_exc)
        is_cancelled = any(e.kind == "cancelled" for e in group_exc)
        is_extra = any(e.kind == "extra" and e.group_id == g.id for e in exceptions)

        expected = (scheduled or is_extra) and not is_holiday and not is_cancelled

        if is_holiday:
            state = "holiday"
        elif is_cancelled:
            state = "cancelled"
        elif not expected:
            state = "not_scheduled"
        else:
            marked = db.scalar(select(func.count(Attendance.id)).where(
                Attendance.group_id == g.id, Attendance.day == d
            )) or 0
            state = "marked" if marked > 0 else "missing"

        students = list(db.scalars(select(User).where(
            User.is_student.is_(True), User.active.is_(True), User.group_id == g.id,
        ).order_by(User.full_name)))

        marks = {a.student_id: a for a in db.scalars(select(Attendance).where(
            Attendance.group_id == g.id, Attendance.day == d
        ))}

        student_list = [{
            "id": s.id,
            "full_name": s.full_name,
            "status": marks[s.id].status if s.id in marks else None,
            "phone": _student_phone(s),
            "parent_phone": _student_parent_phone(s),
        } for s in students]

        counts = {
            "present": sum(1 for x in student_list if x["status"] == "present"),
            "absent": sum(1 for x in student_list if x["status"] == "absent"),
            "excused": sum(1 for x in student_list if x["status"] == "excused"),
            "unmarked": sum(1 for x in student_list if x["status"] is None),
        }
        all_present = (len(students) > 0 and counts["present"] == len(students) and counts["unmarked"] == 0)
        off_schedule = (not scheduled) and (not is_extra)

        sub_tid = effective_teacher_today(db, g, d)
        effective_teacher = teacher_names.get(sub_tid, "") if sub_tid else teacher_names.get(g.teacher_id, "")

        result.append({
            "group_id": g.id,
            "group": g.name,
            "level": g.level,
            "teacher": teacher_names.get(g.teacher_id, ""),
            "effective_teacher": effective_teacher,
            "time": g.lesson_time,
            "expected": expected,
            "state": state,
            "counts": counts,
            "off_schedule": off_schedule,
            "all_present": all_present,
            "students": student_list,
        })

    order = {"missing": 0, "marked": 1, "holiday": 2, "cancelled": 3, "not_scheduled": 4}
    result.sort(key=lambda x: (order.get(x["state"], 9), x["group"]))
    return {"day": d.isoformat(), "groups": result}


@router.get("/day")
def day_state(day: Optional[str] = None, db: Session = Depends(get_db)):
    return _day_state(db, _parse_day(day))


# -------- 2. Matrix --------

def _csv_safe(v: str) -> str:
    if v and v[0] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def _csv_row(cells: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow([_csv_safe(str(c)) if c is not None else "" for c in cells])
    return buf.getvalue()


@router.get("/matrix")
def matrix(
    group_id: int = Query(...),
    month: Optional[str] = None,
    format: Literal["json", "csv"] = "json",
    db: Session = Depends(get_db),
):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(404, "Guruh topilmadi")
    m = _parse_month(month)
    first, last = _month_bounds(m)

    # days: expected lesson days + extra days + any day with marks
    days_set: set[date] = set(expected_days_in_range(db, g, first, last))
    for e in db.scalars(select(LessonException).where(
        LessonException.day >= first, LessonException.day <= last,
        LessonException.kind == "extra",
        or_(LessonException.group_id == g.id, LessonException.group_id.is_(None)),
    )):
        days_set.add(e.day)
    for a in db.scalars(select(Attendance).where(
        Attendance.group_id == g.id, Attendance.day >= first, Attendance.day <= last
    )):
        days_set.add(a.day)
    days = sorted(days_set)

    students = list(db.scalars(select(User).where(
        User.is_student.is_(True), User.active.is_(True), User.group_id == g.id,
    ).order_by(User.full_name)))

    marks: dict[int, dict[str, str]] = {s.id: {} for s in students}
    for a in db.scalars(select(Attendance).where(
        Attendance.group_id == g.id, Attendance.day >= first, Attendance.day <= last
    )):
        if a.student_id in marks:
            marks[a.student_id][a.day.isoformat()] = a.status

    out_students = []
    totals = {"present": 0, "absent": 0, "excused": 0}
    for s in students:
        sm = marks.get(s.id, {})
        p = sum(1 for v in sm.values() if v == "present")
        ab = sum(1 for v in sm.values() if v == "absent")
        ex = sum(1 for v in sm.values() if v == "excused")
        tot = p + ab + ex
        pct = round(100 * p / tot) if tot else 0
        out_students.append({
            "id": s.id, "full_name": s.full_name, "marks": sm,
            "present": p, "absent": ab, "excused": ex, "percent": pct,
        })
        totals["present"] += p; totals["absent"] += ab; totals["excused"] += ex

    payload = {
        "group": {"id": g.id, "name": g.name, "level": g.level},
        "month": m,
        "days": [d.isoformat() for d in days],
        "students": out_students,
        "totals": totals,
    }

    if format == "csv":
        rows = []
        header = ["Oʻquvchi"] + [d.strftime("%d.%m") for d in days] + ["Keldi", "Kelmadi", "Sababli", "%"]
        rows.append(_csv_row(header))
        for st in out_students:
            line = [st["full_name"]]
            for d in days:
                v = st["marks"].get(d.isoformat(), "")
                line.append({"present": "K", "absent": "Y", "excused": "S"}.get(v, ""))
            line += [st["present"], st["absent"], st["excused"], st["percent"]]
            rows.append(_csv_row(line))
        rows.append(_csv_row(["Jami", "", "", "", totals["present"], totals["absent"], totals["excused"], ""]))
        body = "\ufeff" + "".join(rows)
        filename = f"davomat-{g.name}-{m}.csv".replace(" ", "_")
        return Response(
            content=body.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return payload


# -------- 3. Mark (correction) --------

class MarkRecord(BaseModel):
    student_id: int
    status: Literal["present", "absent", "excused"]


class MarkIn(BaseModel):
    group_id: int
    day: date
    records: list[MarkRecord] = Field(min_length=1, max_length=500)
    reason: str = Field(default="", max_length=200)


@router.put("/mark")
def mark(
    body: MarkIn,
    me: User = Depends(finance_user),
    db: Session = Depends(get_db),
):
    g = db.get(Group, body.group_id)
    if not g or not g.active:
        raise HTTPException(404, "Guruh topilmadi")
    today = today_uz()
    if body.day > today:
        raise HTTPException(400, "Kelajak sanaga davomat belgilab boʻlmaydi")
    if body.day < g.created_at.date() if g.created_at else False:
        raise HTTPException(400, "Guruh yaratilishidan oldingi sanaga belgilab boʻlmaydi")

    # check whether any existing row changes
    changes = 0
    for rec in body.records:
        existing = db.scalar(select(Attendance).where(
            Attendance.group_id == g.id, Attendance.student_id == rec.student_id, Attendance.day == body.day
        ))
        if existing and existing.status != rec.status:
            changes += 1

    if changes > 0 and len(body.reason.strip()) < 3:
        raise HTTPException(400, "Oʻzgartirish uchun sabab kamida 3 belgi boʻlishi kerak")

    source = "admin" if me.is_admin else "manager"
    summary = apply_marks(db, me, g, body.day, body.records, source=source, reason=body.reason.strip())
    audit(db, me, "attendance.mark", f"{g.name} {body.day.isoformat()}", f"changes={changes} {summary}")
    db.commit()
    return _day_state(db, body.day)


# -------- 4. Absent + streaks --------

def _latest_followup(db: Session, student_id: int, day: date) -> Optional[dict]:
    f = db.scalar(select(AbsenceFollowup).where(
        AbsenceFollowup.student_id == student_id, AbsenceFollowup.day == day
    ).order_by(AbsenceFollowup.at.desc()))
    if not f:
        return None
    return {"id": f.id, "status": f.status, "note": f.note, "at": f.at.isoformat()}


@router.get("/absent")
def absent(day: Optional[str] = None, db: Session = Depends(get_db)):
    d = _parse_day(day)
    rows = list(db.execute(
        select(Attendance, User, Group)
        .join(User, User.id == Attendance.student_id)
        .join(Group, Group.id == Attendance.group_id)
        .where(Attendance.day == d, Attendance.status == "absent")
        .order_by(Group.name, User.full_name)
    ))
    return {"day": d.isoformat(), "absent": [{
        "student_id": s.id, "full_name": s.full_name,
        "group_id": g.id, "group": g.name,
        "phone": _student_phone(s), "parent_phone": _student_parent_phone(s),
        "followup": _latest_followup(db, s.id, d),
    } for _, s, g in rows]}


@router.get("/streaks")
def streaks(
    min: Optional[int] = None,
    db: Session = Depends(get_db),
):
    threshold = min if min is not None else int(_get_setting(db, "streak_alert_days", "3"))
    threshold = max(1, min(threshold, 30))
    today = today_uz()

    students = list(db.scalars(select(User).where(User.is_student.is_(True), User.active.is_(True))))
    groups = {g.id: g for g in _groups_all(db)}
    marks_map: dict[int, dict[date, str]] = {}
    for a in db.scalars(select(Attendance).where(Attendance.day >= today - timedelta(days=120))):
        marks_map.setdefault(a.student_id, {})[a.day] = a.status

    out = []
    for s in students:
        g = groups.get(s.group_id) if s.group_id else None
        if not g:
            continue
        expected = expected_days_in_range(db, g, today - timedelta(days=60), today)
        expected_desc = list(reversed(expected))
        streak_days = []
        for d in expected_desc:
            status = marks_map.get(s.id, {}).get(d)
            if status == "absent":
                streak_days.append(d.isoformat())
            else:
                break
        if len(streak_days) >= threshold:
            out.append({
                "student_id": s.id, "full_name": s.full_name,
                "group": g.name, "phone": _student_phone(s), "parent_phone": _student_parent_phone(s),
                "days": streak_days,
            })
    out.sort(key=lambda x: len(x["days"]), reverse=True)
    return {"min": threshold, "streaks": out}


# -------- 5. Follow-ups --------

class FollowupIn(BaseModel):
    student_id: int
    day: date
    status: Literal["called", "no_answer", "parent_excused", "note"]
    note: str = Field(default="", max_length=300)


@router.get("/followups")
def list_followups(
    student_id: Optional[int] = None,
    day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(AbsenceFollowup).order_by(AbsenceFollowup.at.desc()).limit(500)
    if student_id:
        stmt = stmt.where(AbsenceFollowup.student_id == student_id)
    if day:
        stmt = stmt.where(AbsenceFollowup.day == _parse_day(day))
    rows = db.scalars(stmt).all()
    return [{"id": f.id, "student_id": f.student_id, "day": f.day.isoformat(),
             "status": f.status, "note": f.note, "at": f.at.isoformat(),
             "by_user_id": f.by_user_id} for f in rows]


@router.post("/followups")
def add_followup(
    body: FollowupIn,
    me: User = Depends(finance_user),
    db: Session = Depends(get_db),
):
    s = db.get(User, body.student_id)
    if not s or not s.is_student:
        raise HTTPException(404, "Oʻquvchi topilmadi")
    f = AbsenceFollowup(
        student_id=body.student_id, day=body.day, status=body.status,
        note=body.note.strip(), by_user_id=me.id,
    )
    db.add(f)
    audit(db, me, "attendance.followup", s.login, f"{body.day.isoformat()} {body.status}")
    db.commit()
    return {
        "id": f.id, "student_id": f.student_id, "day": f.day.isoformat(),
        "status": f.status, "note": f.note, "at": f.at.isoformat(),
        "suggest_excused": body.status == "parent_excused",
    }


# -------- 6. Calendar: exceptions + substitutions --------

class ExceptionIn(BaseModel):
    day: Optional[date] = None
    from_day: Optional[date] = None
    to_day: Optional[date] = None
    group_id: Optional[int] = None
    kind: Literal["holiday", "cancelled", "extra"]
    note: str = Field(default="", max_length=200)


@router.get("/exceptions")
def list_exceptions(
    from_day: Optional[str] = None,
    to_day: Optional[str] = None,
    group_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    stmt = select(LessonException).order_by(LessonException.day.desc()).limit(500)
    if from_day:
        stmt = stmt.where(LessonException.day >= _parse_day(from_day))
    if to_day:
        stmt = stmt.where(LessonException.day <= _parse_day(to_day))
    if group_id is not None:
        stmt = stmt.where(or_(LessonException.group_id == group_id, LessonException.group_id.is_(None)))
    rows = db.scalars(stmt).all()
    return [{"id": e.id, "day": e.day.isoformat(), "group_id": e.group_id,
             "kind": e.kind, "note": e.note} for e in rows]


@router.post("/exceptions")
def create_exception(
    body: ExceptionIn,
    me: User = Depends(finance_user),
    db: Session = Depends(get_db),
):
    if body.group_id is not None:
        if not db.get(Group, body.group_id):
            raise HTTPException(404, "Guruh topilmadi")

    if body.day:
        days = [body.day]
    elif body.from_day and body.to_day:
        if body.to_day < body.from_day:
            raise HTTPException(400, "to_day from_day dan katta boʻlsin")
        if (body.to_day - body.from_day).days > 31:
            raise HTTPException(400, "Maksimal 31 kun")
        days = []
        d = body.from_day
        while d <= body.to_day:
            days.append(d)
            d += timedelta(days=1)
    else:
        raise HTTPException(400, "day yoki from_day+to_day kerak")

    created = 0
    skipped = []
    for d in days:
        # check marks exist for holiday/cancelled
        if body.kind in ("holiday", "cancelled"):
            q = select(func.count(Attendance.id)).where(Attendance.day == d)
            if body.group_id is None:
                q = q.where(Attendance.group_id.in_(select(Group.id).where(Group.active.is_(True))))
            else:
                q = q.where(Attendance.group_id == body.group_id)
            if (db.scalar(q) or 0) > 0:
                skipped.append({"day": d.isoformat(), "reason": "marks_present"})
                continue

        existing = db.scalar(select(LessonException).where(
            LessonException.day == d,
            LessonException.kind == body.kind,
            LessonException.group_id.is_(None) if body.group_id is None else (LessonException.group_id == body.group_id),
        ))
        if existing:
            skipped.append({"day": d.isoformat(), "reason": "duplicate"})
            continue

        db.add(LessonException(
            day=d, group_id=body.group_id, kind=body.kind,
            note=body.note.strip(), created_by=me.id,
        ))
        created += 1

    audit(db, me, "attendance.exception.create", body.kind, f"days={created} skipped={len(skipped)}")
    db.commit()
    if created == 0 and skipped:
        raise HTTPException(409, f"Belgilanmadi: {skipped[0]['reason']}")
    return {"created": created, "skipped": skipped}


@router.delete("/exceptions/{eid}")
def delete_exception(eid: int, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    e = db.get(LessonException, eid)
    if not e:
        raise HTTPException(404, "Topilmadi")
    db.delete(e)
    audit(db, me, "attendance.exception.delete", str(eid))
    db.commit()
    return {"ok": True}


class SubIn(BaseModel):
    group_id: int
    teacher_id: int
    from_day: date
    to_day: date
    reason: str = Field(default="", max_length=200)


@router.get("/substitutions")
def list_subs(db: Session = Depends(get_db)):
    rows = db.scalars(select(GroupSubstitution).order_by(GroupSubstitution.from_day.desc()).limit(200)).all()
    return [{"id": s.id, "group_id": s.group_id, "teacher_id": s.teacher_id,
             "from_day": s.from_day.isoformat(), "to_day": s.to_day.isoformat(),
             "reason": s.reason} for s in rows]


@router.post("/substitutions")
def create_sub(
    body: SubIn,
    me: User = Depends(finance_user),
    db: Session = Depends(get_db),
):
    g = db.get(Group, body.group_id)
    if not g or not g.active:
        raise HTTPException(404, "Guruh topilmadi")
    t = db.get(User, body.teacher_id)
    if not t or not t.is_teacher or not t.active:
        raise HTTPException(400, "Oʻqituvchi topilmadi")
    if body.to_day < body.from_day:
        raise HTTPException(400, "to_day from_day dan katta boʻlsin")
    if has_overlapping_substitution(db, body.group_id, body.from_day, body.to_day):
        raise HTTPException(409, "Bu oraliqda boshqa oʻrinbosarlik bor")

    sub = GroupSubstitution(
        group_id=body.group_id, teacher_id=body.teacher_id,
        from_day=body.from_day, to_day=body.to_day,
        reason=body.reason.strip(), created_by=me.id,
    )
    db.add(sub)
    audit(db, me, "attendance.substitution.create", g.name, f"{body.from_day}..{body.to_day} t={t.login}")
    db.commit()
    return {"id": sub.id, "group_id": sub.group_id, "teacher_id": sub.teacher_id,
            "from_day": sub.from_day.isoformat(), "to_day": sub.to_day.isoformat()}


@router.delete("/substitutions/{sid}")
def delete_sub(sid: int, me: User = Depends(finance_user), db: Session = Depends(get_db)):
    s = db.get(GroupSubstitution, sid)
    if not s:
        raise HTTPException(404, "Topilmadi")
    db.delete(s)
    audit(db, me, "attendance.substitution.delete", str(sid))
    db.commit()
    return {"ok": True}


# -------- 7. Suspicious batches --------

@router.get("/suspicious")
def suspicious(
    from_day: Optional[str] = None,
    to_day: Optional[str] = None,
    db: Session = Depends(get_db),
):
    today = today_uz()
    f = _parse_day(from_day) if from_day else (today - timedelta(days=30))
    t = _parse_day(to_day) if to_day else today

    batches = list(db.scalars(select(AttendanceBatch).where(
        AttendanceBatch.day >= f, AttendanceBatch.day <= t
    )))
    groups = {g.id: g for g in _groups_all(db)}
    teachers = _teacher_names(db)

    per: dict[tuple[int, int], dict] = {}
    for b in batches:
        key = (b.group_id, b.teacher_id or 0)
        d = per.setdefault(key, {"total": 0, "all_present": 0})
        d["total"] += 1
        if b.all_present:
            d["all_present"] += 1

    flagged = []
    for (gid, tid), d in per.items():
        if d["total"] >= 8 and d["all_present"] / d["total"] >= 0.9:
            flagged.append({
                "group": groups.get(gid).name if gid in groups else "",
                "group_id": gid,
                "teacher": teachers.get(tid, ""),
                "teacher_id": tid,
                "batches": d["total"],
                "all_present": d["all_present"],
                "percent": round(100 * d["all_present"] / d["total"]),
            })
    flagged.sort(key=lambda x: x["percent"], reverse=True)

    rows = [{
        "group": groups.get(k[0]).name if k[0] in groups else "",
        "teacher": teachers.get(k[1], ""),
        "batches": v["total"], "all_present": v["all_present"],
        "percent": round(100 * v["all_present"] / v["total"]) if v["total"] else 0,
    } for k, v in per.items()]
    rows.sort(key=lambda x: x["percent"], reverse=True)

    return {"from": f.isoformat(), "to": t.isoformat(), "rows": rows, "flagged": flagged}


# -------- 8. Summary (TZ-3 dashboard fallback) --------

@router.get("/summary")
def summary(day: Optional[str] = None, db: Session = Depends(get_db)):
    d = _parse_day(day)
    state = _day_state(db, d)
    missing = [{"group_id": g["group_id"], "group": g["group"], "teacher": g["effective_teacher"]}
               for g in state["groups"] if g["state"] == "missing"]
    marked = sum(1 for g in state["groups"] if g["state"] == "marked")
    return {
        "today": d.isoformat(),
        "groups_with_lesson": sum(1 for g in state["groups"] if g["expected"]),
        "marked": marked,
        "missing": missing,
        "present_total": sum(g["counts"]["present"] for g in state["groups"]),
        "absent_total": sum(g["counts"]["absent"] for g in state["groups"]),
    }
