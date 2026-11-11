"""Regression: teacher pull/push shapes unchanged + substitute visibility."""
from datetime import date, timedelta

from app.security import hash_password
from app.db import SessionLocal
from app.models import User

from tests.conftest import _auth, _login, make_group, make_manager, make_student, make_teacher


def _teacher_login(client, admin_token, login="tchA"):
    make_teacher(client, admin_token, login)
    # set known password directly
    with SessionLocal() as db:
        u = db.query(User).filter(User.login == login).first()
        u.password_hash = hash_password("TchPass123!")
        db.commit()
    return _login(client, login, "TchPass123!")


def test_teacher_pull_shape(client, admin_token):
    ttoken = _teacher_login(client, admin_token, "tchA")
    make_group(client, admin_token, name="T1", days="135", teacher_login="tchA")
    r = client.get("/api/teacher/pull", headers=_auth(ttoken))
    assert r.status_code == 200
    d = r.json()
    assert "groups" in d and "attendance" in d and "tasks" in d
    assert len(d["groups"]) >= 1
    g = d["groups"][0]
    assert "substitute" in g  # new field


def test_teacher_push_attendance(client, admin_token):
    ttoken = _teacher_login(client, admin_token, "tchB")
    g = make_group(client, admin_token, name="T2", days="135", teacher_login="tchB")
    s = make_student(client, admin_token, g["id"], name="T2Stud")
    day = date.today().isoformat()
    r = client.post("/api/teacher/push", json={
        "actions": [{
            "uid": "uid-test-001",
            "type": "attendance",
            "data": {"group_id": g["id"], "date": day, "records": [
                {"student_id": s["user"]["id"], "status": "present"},
            ]},
        }],
    }, headers=_auth(ttoken))
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "ok"


def test_teacher_push_blocked_on_holiday(client, admin_token):
    mgr_pwd = make_manager(client, admin_token, "mgrT")
    mt = _login(client, "mgrT", mgr_pwd)
    ttoken = _teacher_login(client, admin_token, "tchC")
    g = make_group(client, admin_token, name="T3", days="1234567", teacher_login="tchC")
    s = make_student(client, admin_token, g["id"], name="T3Stud")
    day = date.today().isoformat()
    client.post("/api/attendance/exceptions", json={
        "day": day, "kind": "holiday", "group_id": g["id"], "note": "",
    }, headers=_auth(mt))
    r = client.post("/api/teacher/push", json={
        "actions": [{
            "uid": "uid-test-002",
            "type": "attendance",
            "data": {"group_id": g["id"], "date": day, "records": [
                {"student_id": s["user"]["id"], "status": "present"},
            ]},
        }],
    }, headers=_auth(ttoken))
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["status"] == "rejected"
    assert "dam olish" in res["error"].lower()
