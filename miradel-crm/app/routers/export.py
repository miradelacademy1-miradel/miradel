"""TZ-3: Backup export as ZIP of CSVs."""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Generator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import (
    Announcement, Artifact, Attendance, AuditLog, ChatMessage, ChatThread, Group,
    LessonReport, Payment, PointsLedger, SalaryPayout, Setting, Submission, Task,
    User, UserArtifact, WorkPlan,
)
from .admin import audit

router = APIRouter(prefix="/api/admin", tags=["export"], dependencies=[Depends(require_admin)])


def _csv_escape(v) -> str:
    if v is None:
        return ""
    s = str(v)
    if s and s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s


def _write_csv_to_zip(zf: zipfile.ZipFile, table_name: str, columns: list, query, db: Session) -> int:
    """Write a table to a CSV file inside the zip. Returns row count."""
    count = 0
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(columns)
    
    for obj in db.scalars(query).yield_per(1000):
        row = []
        for col in columns:
            val = getattr(obj, col, None)
            if isinstance(val, datetime):
                val = val.astimezone(timezone.utc).isoformat()
            elif isinstance(val, bool):
                val = "true" if val else "false"
            elif hasattr(val, "isoformat"):
                val = val.isoformat()
            row.append(_csv_escape(val))
        w.writerow(row)
        count += 1
    
    zf.writestr(f"{table_name}.csv", "\ufeff" + buf.getvalue())
    return count


def _generate_zip(db: Session, include_chat: bool) -> Generator[bytes, None, None]:
    """Generator yielding chunks of the ZIP file."""
    buf = io.BytesIO()
    tables = {}
    
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Users: exclude password_hash, token_version
        user_cols = ["id", "login", "full_name", "phone", "parent_phone", "is_admin", "is_manager", "is_teacher", "is_student",
                     "group_id", "level", "active", "must_change_password", "started_on", "monthly_fee", "fee_day",
                     "salary_mode", "salary_rate", "created_at", "updated_at"]
        tables["users"] = _write_csv_to_zip(zf, "users", user_cols, select(User).order_by(User.id), db)
        
        tables["groups"] = _write_csv_to_zip(zf, "groups", ["id", "name", "course", "level", "days", "lesson_time", "monthly_fee", "teacher_id", "active", "created_at", "updated_at"], select(Group).order_by(Group.id), db)
        
        # Attendance
        tables["attendance"] = _write_csv_to_zip(zf, "attendance", ["id", "group_id", "student_id", "day", "status", "marked_by", "off_schedule", "source", "updated_at"], select(Attendance).order_by(Attendance.id), db)
        
        # Payments
        tables["payments"] = _write_csv_to_zip(zf, "payments", ["id", "student_id", "month", "amount", "method", "course", "note", "paid_on", "voided", "created_by", "created_at"], select(Payment).order_by(Payment.id), db)
        
        # Salary Payouts
        tables["salary_payouts"] = _write_csv_to_zip(zf, "salary_payouts", ["id", "teacher_id", "month", "amount", "note", "paid_on", "created_by", "created_at"], select(SalaryPayout).order_by(SalaryPayout.id), db)
        
        # Tasks
        tables["tasks"] = _write_csv_to_zip(zf, "tasks", ["id", "title", "body", "kind", "level", "group_id", "points", "due_date", "artifact_id", "active", "created_by", "created_at", "updated_at"], select(Task).order_by(Task.id), db)
        
        # Submissions
        tables["submissions"] = _write_csv_to_zip(zf, "submissions", ["id", "task_id", "student_id", "answer", "points_awarded", "client_uid", "created_at"], select(Submission).order_by(Submission.id), db)
        
        # Points Ledger
        tables["points_ledger"] = _write_csv_to_zip(zf, "points_ledger", ["id", "student_id", "source", "ref_id", "points", "note", "created_at"], select(PointsLedger).order_by(PointsLedger.id), db)
        
        # Announcements
        tables["announcements"] = _write_csv_to_zip(zf, "announcements", ["id", "title", "body", "group_id", "created_by", "active", "created_at", "updated_at"], select(Announcement).order_by(Announcement.id), db)
        
        # Artifacts
        tables["artifacts"] = _write_csv_to_zip(zf, "artifacts", ["id", "name", "icon", "description", "active", "created_at"], select(Artifact).order_by(Artifact.id), db)
        
        # User Artifacts
        tables["user_artifacts"] = _write_csv_to_zip(zf, "user_artifacts", ["id", "student_id", "artifact_id", "earned_at"], select(UserArtifact).order_by(UserArtifact.id), db)
        
        # Lesson Reports
        tables["lesson_reports"] = _write_csv_to_zip(zf, "lesson_reports", ["id", "group_id", "teacher_id", "day", "topic", "notes", "created_at"], select(LessonReport).order_by(LessonReport.id), db)
        
        # Work Plans
        tables["work_plans"] = _write_csv_to_zip(zf, "work_plans", ["id", "teacher_id", "title", "due_date", "status", "done_at", "created_by", "created_at", "updated_at"], select(WorkPlan).order_by(WorkPlan.id), db)
        
        # Settings
        tables["settings"] = _write_csv_to_zip(zf, "settings", ["key", "value"], select(Setting), db)
        
        # Audit Log
        tables["audit_log"] = _write_csv_to_zip(zf, "audit_log", ["id", "actor_id", "action", "target", "detail", "created_at"], select(AuditLog).order_by(AuditLog.id), db)
        
        if include_chat:
            tables["chat_threads"] = _write_csv_to_zip(zf, "chat_threads", ["id", "key", "kind", "group_id", "student_id", "teacher_id", "created_at"], select(ChatThread).order_by(ChatThread.id), db)
            tables["chat_messages"] = _write_csv_to_zip(zf, "chat_messages", ["id", "thread_id", "sender_id", "body", "client_uid", "deleted", "created_at"], select(ChatMessage).order_by(ChatMessage.id), db)

        # Manifest
        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": "admin",
            "app_version": "1.0",
            "tables": tables,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    
    buf.seek(0)
    while chunk := buf.read(1024 * 1024): # 1MB chunks
        yield chunk


@router.get("/export")
def export_backup(
    chat: bool = Query(False),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Audit entry
    audit(db, admin, "export.backup", f"chat={chat}")
    db.commit()

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"miradel-backup-{date_str}.zip"
    
    return StreamingResponse(
        _generate_zip(db, chat),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
