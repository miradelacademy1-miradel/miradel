from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import read_token

bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Kirish talab qilinadi")
    parsed = read_token(cred.credentials)
    user = db.get(User, parsed[0]) if parsed else None
    if not user or not user.active or (user.token_version or 0) != parsed[1]:
        raise HTTPException(401, "Sessiya yaroqsiz")
    return user


def require_admin(u: User = Depends(current_user)) -> User:
    if not u.is_admin:
        raise HTTPException(403, "Faqat admin uchun")
    return u


def require_manager(u: User = Depends(current_user)) -> User:
    if not u.is_manager:
        raise HTTPException(403, "Faqat menejer uchun")
    return u


def require_teacher(u: User = Depends(current_user)) -> User:
    if not u.is_teacher:
        raise HTTPException(403, "Faqat oʻqituvchi uchun")
    return u


def panels(u: User) -> list:
    out = []
    if u.is_student:
        out.append("student")
    if u.is_teacher:
        out.append("teacher")
    if u.is_manager:
        out.append("manager")
    if u.is_admin:
        out.append("admin")
    return out


def user_out(u: User) -> dict:
    return {
        "id": u.id, "login": u.login, "full_name": u.full_name, "phone": u.phone,
        "is_admin": u.is_admin, "is_manager": u.is_manager, "is_teacher": u.is_teacher,
        "is_student": u.is_student, "group_id": u.group_id, "level": u.level,
        "active": u.active, "must_change_password": u.must_change_password,
        "panels": panels(u),
    }
