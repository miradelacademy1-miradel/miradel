from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, user_out
from ..models import User
from ..security import clear, fail, hash_password, locked, make_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=100)


class PwdIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=100)


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    login_name = body.login.strip().lower()
    ip = request.client.host if request.client else "?"
    key = f"{login_name}|{ip}"
    wait = locked(key)
    if wait:
        raise HTTPException(429, f"Juda koʻp urinish. {wait} soniyadan keyin urining")
    user = db.scalar(select(User).where(User.login == login_name))
    if not user or not user.active or not verify_password(user.password_hash, body.password):
        fail(key)
        raise HTTPException(401, "Login yoki parol notoʻgʻri")
    clear(key)
    return {"token": make_token(user.id), "user": user_out(user)}


@router.get("/me")
def me(u: User = Depends(current_user)):
    return user_out(u)


@router.post("/change-password")
def change_password(body: PwdIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(u.password_hash, body.old_password):
        raise HTTPException(400, "Eski parol notoʻgʻri")
    u.password_hash = hash_password(body.new_password)
    u.must_change_password = False
    db.commit()
    return {"ok": True}
