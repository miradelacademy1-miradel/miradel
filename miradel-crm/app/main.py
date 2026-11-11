import logging
from contextlib import asynccontextmanager
from pathlib import Path

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import models
from .config import ADMIN_LOGIN, ADMIN_PASSWORD
from .db import SessionLocal
from .migrate import ensure_schema
from .routers import admin, appinfo, attendance, auth, chat, content, manager, sync, teacher
from .security import hash_password

log = logging.getLogger("miradel")
STATIC = Path(__file__).resolve().parent.parent / "static"


def seed_admin():
    with SessionLocal() as db:
        if db.scalar(select(models.User).where(models.User.is_admin.is_(True))):
            return
        if not ADMIN_PASSWORD:
            log.warning("Admin yoʻq va ADMIN_PASSWORD berilmagan: admin yaratilmadi")
            return
        db.add(models.User(login=ADMIN_LOGIN, password_hash=hash_password(ADMIN_PASSWORD),
                           full_name="Administrator", is_admin=True))
        db.commit()
        log.info("Admin yaratildi: %s", ADMIN_LOGIN)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    seed_admin()
    yield


app = FastAPI(title="Miradel CRM", lifespan=lifespan)
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "https://localhost,capacitor://localhost,http://localhost").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=False, max_age=600)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(content.router)
app.include_router(sync.router)
app.include_router(teacher.router)
app.include_router(manager.router)
app.include_router(attendance.router)
app.include_router(chat.router)
app.include_router(chat.admin_router)
app.include_router(appinfo.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")


app.mount("/download", StaticFiles(directory=STATIC / "download", html=True), name="download")
app.mount("/admin", StaticFiles(directory=STATIC / "admin", html=True), name="admin")
app.mount("/panel", StaticFiles(directory=STATIC / "panel", html=True), name="panel")
app.mount("/app", StaticFiles(directory=STATIC / "app", html=True), name="app")
