"""TZ-3: Export ZIP acceptance criteria."""
import io
import zipfile
import json
import pytest
from tests.conftest import _auth, make_group, make_student

def test_export_zip_structure(client, admin_token):
    """AC1: Export contains all listed CSVs and manifest.json."""
    g = make_group(client, admin_token, name="ExpG")
    s = make_student(client, admin_token, g["id"], name="ExpStud")
    
    r = client.get("/api/admin/export", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    
    assert "manifest.json" in names
    assert "users.csv" in names
    assert "groups.csv" in names
    assert "payments.csv" in names
    assert "attendance.csv" in names
    
    # Check manifest
    manifest = json.loads(zf.read("manifest.json"))
    assert "users" in manifest["tables"]
    assert manifest["tables"]["users"] >= 1
    
    # Check users.csv does not have password_hash
    users_csv = zf.read("users.csv").decode("utf-8-sig")
    lines = users_csv.strip().split("\n")
    assert "password_hash" not in lines[0]
    assert "token_version" not in lines[0]

def test_export_audit_entry(client, admin_token):
    """AC1: Audit entry written."""
    client.get("/api/admin/export", headers=_auth(admin_token))
    r = client.get("/api/admin/audit", headers=_auth(admin_token))
    assert any("export.backup" in x["action"] for x in r.json())

def test_export_chat_flag(client, admin_token):
    """AC1: ?chat=1 adds chat tables."""
    r = client.get("/api/admin/export?chat=1", headers=_auth(admin_token))
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "chat_threads.csv" in zf.namelist()
    assert "chat_messages.csv" in zf.namelist()
