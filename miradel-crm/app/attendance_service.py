"""Shared attendance logic for teacher push and manager/admin endpoints."""
from datetime import date, timedelta
from typing import Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .finance import today_uz
from .models import (
    Attendance, AttendanceBatch, AttendanceLog, Group, LessonException,
    PointsLedger, Setting, User,
)

VALID_STATUSES = ("present", "absent", "excused")


def _get_setting(db: Session, key: str, default: str) -> str:
    s = db.get(Setting, key)
    return s.value if s else default


def is_scheduled_day(group: Group, day: date) -> bool:
    return str(day.isoweekday()) in (group.days or "")


def _exception_for(db: Session, group_id: int, day: date, kind: str) -> bool:
    return db.scalar(select(LessonException.id).where(
        LessonException.day == day,
        LessonException.kind == kind,
        or_(LessonException.group_id == group_id, LessonException.group_id.is_(None)),
    )) is not None


def is_expected_day(db: Session, group: Group, day: date) -> bool:
    if _exception_for(db, group.id, day, "holiday"):
        return False
    if _exception_for(db, group.id, day, "cancelled"):
        return False
    if _exception_for(db, group.id, day, "extra"):
        return True
    return is_scheduled_day(group, day)


def is_off_schedule(db: Session, group: Group, day: date) -> bool:
    return (not is_scheduled_day(group, day)) and (not _exception_for(db, group.id, day, "extra"))


def expected_days_in_range(db: Session, group: Group, from_day: date, to_day: date) -> list[date]:
    """List of expected lesson days in [from_day, to_day] (inclusive), skipping holidays/cancelled."""
    out: list[date] = []
    d = from_day
    while d <= to_day:
        if is_expected_day(db, group, d):
            out.append(d)
        d += timedelta(days=1)
    return out


def apply_marks(
    db: Session,
    actor: User,
    group: Group,
    day: date,
    records: Iterable,
    source: str,
    reason: str = "",
    client_uid: str = "",
) -> dict:
    """Apply attendance marks for a group on a day.

    `records` is an iterable of objects with `.student_id` and `.status`.
    Returns summary dict {present, absent, excused, total, all_present, off_schedule}.
    """
    if source not in ("teacher", "manager", "admin"):
        source = "teacher"

    points_mode = _get_setting(db, "attendance_points_mode", "all")
    try:
        pp = int(_get_setting(db, "attendance_points", "2"))
    except ValueError:
        pp = 2

    off_schedule = is_off_schedule(db, group, day)

    ok_ids = {s.id for s in db.scalars(select(User).where(
        User.is_student.is_(True), User.group_id == group.id
    ))}
    total = len(ok_ids)

    counts = {"present": 0, "absent": 0, "excused": 0}

    for r in records:
        sid = getattr(r, "student_id", None)
        status = getattr(r, "status", None)
        if sid is None or status not in VALID_STATUSES or sid not in ok_ids:
            continue

        row = db.scalar(select(Attendance).where(
            Attendance.group_id == group.id,
            Attendance.student_id == sid,
            Attendance.day == day,
        ))

        if row and row.status == status:
            counts[status] += 1
            continue

        old_status = row.status if row else None

        if row:
            for old in db.scalars(select(PointsLedger).where(
                PointsLedger.source == "attendance",
                PointsLedger.ref_id == row.id,
            )):
                db.delete(old)
            row.status = status
            row.marked_by = actor.id
            row.off_schedule = off_schedule
            row.source = source
        else:
            row = Attendance(
                group_id=group.id,
                student_id=sid,
                day=day,
                status=status,
                marked_by=actor.id,
                off_schedule=off_schedule,
                source=source,
            )
            db.add(row)
            db.flush()

        counts[status] += 1

        db.add(AttendanceLog(
            group_id=group.id,
            student_id=sid,
            day=day,
            old_status=old_status,
            new_status=status,
            by_user_id=actor.id,
            source=source,
            reason=(reason or "")[:200],
        ))

        award = status == "present" and pp > 0
        if award and points_mode == "scheduled_only" and off_schedule:
            award = False
        if award:
            db.add(PointsLedger(
                student_id=sid,
                source="attendance",
                ref_id=row.id,
                points=pp,
                note=f"Davomat {day.isoformat()}",
            ))

    all_present = (total > 0 and counts["present"] == total)

    db.add(AttendanceBatch(
        group_id=group.id,
        day=day,
        teacher_id=actor.id,
        total=total,
        present=counts["present"],
        absent=counts["absent"],
        excused=counts["excused"],
        all_present=all_present,
        source=source,
        client_uid=(client_uid or "")[:60],
    ))

    return {
        "present": counts["present"],
        "absent": counts["absent"],
        "excused": counts["excused"],
        "total": total,
        "all_present": all_present,
        "off_schedule": off_schedule,
    }


def effective_teacher_today(db: Session, group: Group, day: date) -> Optional[int]:
    """Return substitute teacher id if one is active for `day`, else None."""
    from .models import GroupSubstitution
    sub = db.scalar(select(GroupSubstitution).where(
        GroupSubstitution.group_id == group.id,
        GroupSubstitution.from_day <= day,
        GroupSubstitution.to_day >= day,
    ).order_by(GroupSubstitution.from_day))
    return sub.teacher_id if sub else None


def is_substitute_today(db: Session, group: Group, teacher_id: int, day: date) -> bool:
    from .models import GroupSubstitution
    return db.scalar(select(GroupSubstitution.id).where(
        GroupSubstitution.group_id == group.id,
        GroupSubstitution.teacher_id == teacher_id,
        GroupSubstitution.from_day <= day,
        GroupSubstitution.to_day >= day,
    )) is not None


def has_overlapping_substitution(
    db: Session, group_id: int, from_day: date, to_day: date, ignore_id: Optional[int] = None
) -> bool:
    from .models import GroupSubstitution
    stmt = select(GroupSubstitution.id).where(
        GroupSubstitution.group_id == group_id,
        GroupSubstitution.from_day <= to_day,
        GroupSubstitution.to_day >= from_day,
    )
    if ignore_id:
        stmt = stmt.where(GroupSubstitution.id != ignore_id)
    return db.scalar(stmt) is not None
