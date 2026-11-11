import asyncio
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
from .config import ADMIN_LOGIN, ADMIN_PASSWORD, ENV
from .db import SessionLocal
from .finance import month_of, today_uz
from .migrate import ensure_schema
from .routers import admin, appinfo, attendance, auth, chat, content, export, invoices, manager, payment_settings, reports, sync, teacher
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


async def invoice_generator_task():
    if ENV != "prod":
        return
    from .invoices_service import generate_month
    while True:
        try:
            with SessionLocal() as db:
                result = generate_month(db, month_of(today_uz()))
                log.info("Invoice generation: %s", result)
        except Exception:
            log.exception("Invoice generation failed")
        await asyncio.sleep(86400)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema()
    seed_admin()
    task = asyncio.create_task(invoice_generator_task())
    try:
        yield
    finally:
        task.cancel()


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
app.include_router(invoices.router)
app.include_router(payment_settings.router)
app.include_router(reports.router)
app.include_router(export.router)
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
