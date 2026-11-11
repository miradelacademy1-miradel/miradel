import os
import tempfile

_db_path = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db_path}")
os.environ.setdefault("ADMIN_PASSWORD", "testadmin123")
os.environ.setdefault("SECRET_KEY", "test-secret-key-min-32-chars-please")
os.environ.setdefault("ENV", "dev")

import pytest
from fastapi.testclient import TestClient

from app import security
from app.db import Base, SessionLocal, engine
from app.main import app
from app.migrate import ensure_schema
from app.routers import admin as admin_router
from app.seed import seed_admin


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    ensure_schema()
    seed_admin()
    security._FAILS.clear()
    with TestClient(app) as c:
        yield c


def _login(client, login, password):
    r = client.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_token(client):
    return _login(client, "admin", "testadmin123")


def _create_user(client, token, **kw):
    r = client.post("/api/admin/students", json=kw, headers=_auth(token))
    if r.status_code == 404:
        # fallback: create via admin staff endpoint
        r = client.post("/api/admin/staff", json=kw, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def make_manager(client, admin_token, login="mgr1"):
    r = client.post("/api/admin/staff", json={
        "full_name": "Manager One", "phone": "", "login": login,
        "is_teacher": False, "is_manager": True,
    }, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()["password"]


def make_teacher(client, admin_token, login="tch1"):
    r = client.post("/api/admin/staff", json={
        "full_name": "Teacher One", "phone": "", "login": login,
        "is_teacher": True, "is_manager": False,
    }, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()["password"]


def make_group(client, admin_token, name="G1", days="135", teacher_login=None):
    body = {"name": name, "course": "Ingliz", "level": "Beginner", "days": days, "lesson_time": "15:00"}
    if teacher_login:
        # find teacher id
        r = client.get("/api/admin/staff", headers=_auth(admin_token))
        staff = r.json()
        tid = next((s["id"] for s in staff if s["login"] == teacher_login), None)
        if tid:
            body["teacher_id"] = tid
    r = client.post("/api/admin/groups", json=body, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()


def make_student(client, admin_token, group_id, name="Ali"):
    r = client.post("/api/admin/students", json={
        "full_name": name, "phone": "", "group_id": group_id, "level": "",
    }, headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    return r.json()
