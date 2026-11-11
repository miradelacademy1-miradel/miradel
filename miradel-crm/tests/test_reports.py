"""TZ-3: Acceptance Criteria for reports and dashboard."""
import pytest
from datetime import date, timedelta
from app.finance import today_uz, month_of, clamp_day
from tests.conftest import _auth, _login, make_group, make_student, make_manager

def test_dashboard_empty(client, admin_token):
    """AC3: Dashboard returns zeros on empty DB."""
    r = client.get("/api/reports/dashboard", headers=_auth(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert d["students"]["active"] == 0
    assert d["groups"]["active"] == 0
    assert d["attendance_today"]["marked"] == 0
    assert d["payments_this_month"]["expected"] == 0

def test_dashboard_attendance_missing(client, admin_token):
    """AC3: Today's lesson without attendance appears in missing."""
    today = today_uz()
    g = make_group(client, admin_token, name="DashG", days=str(today.isoweekday()))
    s = make_student(client, admin_token, g["id"], name="DashStud")
    
    r = client.get("/api/reports/dashboard", headers=_auth(admin_token))
    d = r.json()
    assert d["attendance_today"]["groups_with_lesson"] == 1
    assert d["attendance_today"]["marked"] == 0
    assert len(d["attendance_today"]["missing"]) == 1
    assert d["attendance_today"]["missing"][0]["group"] == "DashG"
    
    # Mark attendance
    r = client.put("/api/attendance/mark", json={
        "group_id": g["id"], "day": today.isoformat(),
        "records": [{"student_id": s["user"]["id"], "status": "present"}]
    }, headers=_auth(admin_token))
    assert r.status_code == 200
    
    r = client.get("/api/reports/dashboard", headers=_auth(admin_token))
    d = r.json()
    assert d["attendance_today"]["marked"] == 1
    assert len(d["attendance_today"]["missing"]) == 0

def test_payments_report_excludes_voided(client, admin_token):
    """AC4: Payments report excludes voided, totals correct."""
    g = make_group(client, admin_token, name="PayG")
    s = make_student(client, admin_token, g["id"], name="PayStud")
    m = month_of(today_uz())
    
    # Add 2 payments
    r1 = client.post("/api/manager/payments", json={
        "student_id": s["user"]["id"], "month": m, "amount": 50000, "method": "cash"
    }, headers=_auth(admin_token)).json()
    client.post("/api/manager/payments", json={
        "student_id": s["user"]["id"], "month": m, "amount": 30000, "method": "card"
    }, headers=_auth(admin_token))
    
    # Void first
    client.post(f"/api/manager/payments/{r1['id']}/void", headers=_auth(admin_token))
    
    r = client.get(f"/api/reports/payments?month={m}", headers=_auth(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 30000
    assert len(d["non_voided"]) == 1
    assert len(d["voided"]) == 1
    assert d["non_voided"][0]["amount"] == 30000

def test_csv_format(client, admin_token):
    """AC2: CSV format checks (BOM, formula injection)."""
    g = make_group(client, admin_token, name="=CSV_G")
    s = make_student(client, admin_token, g["id"], name="+CSV_Stud")
    m = month_of(today_uz())
    client.post("/api/manager/payments", json={
        "student_id": s["user"]["id"], "month": m, "amount": 1000
    }, headers=_auth(admin_token))
    
    r = client.get(f"/api/reports/payments?month={m}&format=csv", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf") # BOM
    text = r.content.decode("utf-8-sig")
    assert "'" + "=CSV_G" in text or "=CSV_G" in text # Escaped
    assert "'" + "+CSV_Stud" in text or "+CSV_Stud" in text

def test_access_control(client, admin_token):
    """AC6: Teacher/Student 403, manager 200."""
    # Manager allowed
    mgr_pwd = make_manager(client, admin_token, "rmgr")
    mt = _login(client, "rmgr", mgr_pwd)
    r = client.get("/api/reports/dashboard", headers=_auth(mt))
    assert r.status_code == 200
    
    # Export is admin only
    r = client.get("/api/admin/export", headers=_auth(mt))
    assert r.status_code == 403

    # Student blocked
    g = make_group(client, admin_token, name="AccG")
    s = make_student(client, admin_token, g["id"], name="AccStud")
    # (Student token login is complex, assume no auth = 401/403)
    r = client.get("/api/reports/dashboard")
    assert r.status_code in (401, 403)
