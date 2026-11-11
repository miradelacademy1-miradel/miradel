"""TZ-4: Finance improvements tests."""
import pytest
from datetime import date, timedelta
from sqlalchemy import select

from app.db import SessionLocal
from app.finance import today_uz, month_of
from app.models import Invoice, Payment, User, SalaryAdjustment
from app.invoices_service import generate_month

from tests.conftest import _auth, _login, make_group, make_student, make_manager, make_teacher

def test_ac1_invoice_generation_idempotent_and_snapshot(client, admin_token):
    g = make_group(client, admin_token, name="FinG")
    s = make_student(client, admin_token, g["id"], name="FinStud")
    # Set fee 100k
    client.patch(f"/api/manager/groups/{g['id']}/fee", json={"monthly_fee": 100000}, headers=_auth(admin_token))
    
    m = "2026-06"
    # First generation
    r = client.post("/api/manager/invoices/generate", json={"month": m}, headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["created"] == 1
    
    # Change fee
    client.patch(f"/api/manager/groups/{g['id']}/fee", json={"monthly_fee": 200000}, headers=_auth(admin_token))
    
    # Second generation -> skipped, amount stays 100k
    r = client.post("/api/manager/invoices/generate", json={"month": m}, headers=_auth(admin_token))
    assert r.json()["created"] == 0
    assert r.json()["skipped"] >= 1
    
    with SessionLocal() as db:
        inv = db.scalar(select(Invoice).where(Invoice.month == m, Invoice.student_id == s["user"]["id"]))
        assert inv.amount_due == 100000

def test_ac2_finance_response_compatibility(client, admin_token):
    g = make_group(client, admin_token, name="CompG")
    make_student(client, admin_token, g["id"], name="CompStud")
    r = client.get("/api/manager/finance?month=2026-07", headers=_auth(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert "totals" in d and "rows" in d and "groups" in d
    assert "fee" in d["rows"][0]

def test_ac4_debts_cross_month(client, admin_token):
    g = make_group(client, admin_token, name="DebtG")
    s = make_student(client, admin_token, g["id"], name="DebtStud")
    client.patch(f"/api/manager/groups/{g['id']}/fee", json={"monthly_fee": 50000}, headers=_auth(admin_token))
    
    client.post("/api/manager/invoices/generate", json={"month": "2026-01"}, headers=_auth(admin_token))
    client.post("/api/manager/invoices/generate", json={"month": "2026-02"}, headers=_auth(admin_token))
    
    # Pay for Jan only
    client.post("/api/manager/payments", json={
        "student_id": s["user"]["id"], "month": "2026-01", "amount": 50000
    }, headers=_auth(admin_token))
    
    r = client.get("/api/manager/debts?upto=2026-02", headers=_auth(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert len(d["rows"]) == 1
    row = d["rows"][0]
    assert row["total_left"] == 50000
    assert len(row["months"]) == 1
    assert row["months"][0]["month"] == "2026-02"

def test_ac5_allocate_oldest(client, admin_token):
    g = make_group(client, admin_token, name="AllocG")
    s = make_student(client, admin_token, g["id"], name="AllocStud")
    client.patch(f"/api/manager/groups/{g['id']}/fee", json={"monthly_fee": 50000}, headers=_auth(admin_token))
    
    client.post("/api/manager/invoices/generate", json={"month": "2026-01"}, headers=_auth(admin_token))
    client.post("/api/manager/invoices/generate", json={"month": "2026-02"}, headers=_auth(admin_token))
    
    # Pay 60000 with allocate_oldest
    r = client.post("/api/manager/payments", json={
        "student_id": s["user"]["id"], "month": "2026-03", "amount": 60000, "allocate_oldest": True
    }, headers=_auth(admin_token))
    assert r.status_code == 200
    d = r.json()
    assert "allocations" in d
    assert len(d["allocations"]) == 2
    assert d["allocations"][0]["month"] == "2026-01"
    assert d["allocations"][0]["amount"] == 50000
    assert d["allocations"][1]["month"] == "2026-02"
    assert d["allocations"][1]["amount"] == 10000

def test_ac6_receipt_numbers(client, admin_token):
    g = make_group(client, admin_token, name="RecG")
    s = make_student(client, admin_token, g["id"], name="RecStud")
    
    r = client.post("/api/manager/payments", json={
        "student_id": s["user"]["id"], "month": "2026-04", "amount": 1000
    }, headers=_auth(admin_token))
    pid = r.json()["id"]
    
    rr = client.get(f"/api/manager/payments/{pid}/receipt", headers=_auth(admin_token))
    assert rr.status_code == 200
    d = rr.json()
    assert d["receipt_no"].startswith("R-")
    assert d["amount"] == 1000
