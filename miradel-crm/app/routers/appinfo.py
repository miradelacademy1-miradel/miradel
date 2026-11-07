"""Android ilova versiyasi: yangi APK chiqqanda ilova eslatma koʻrsatishi uchun.
Manba: (1) APK_URL + APK_VERSION muhit oʻzgaruvchilari yoki (2) GitHub Releases (GITHUB_REPO=egasi/repo)."""
import json
import os
import time
import urllib.request

from fastapi import APIRouter

router = APIRouter(prefix="/api/app", tags=["app"])
_CACHE = {"t": 0.0, "v": None}
TTL = 600


def _from_github(repo: str):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "miradel-crm"})
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=5) as r:
        d = json.loads(r.read().decode("utf-8"))
    tag = str(d.get("tag_name", ""))
    digits = "".join(ch for ch in tag if ch.isdigit())
    url = None
    for a in d.get("assets", []):
        if str(a.get("name", "")).lower().endswith(".apk"):
            url = a.get("browser_download_url")
            break
    return {"version_code": int(digits) if digits else 0, "version_name": tag, "apk_url": url, "notes": (d.get("body") or "")[:500]}


def _latest():
    if os.getenv("APK_URL"):
        code = int(os.getenv("APK_VERSION", "0") or 0)
        return {"version_code": code, "version_name": str(code), "apk_url": os.getenv("APK_URL"), "notes": os.getenv("APK_NOTES", "")}
    repo = os.getenv("GITHUB_REPO")
    if not repo:
        return {"version_code": 0, "version_name": "", "apk_url": None, "notes": ""}
    if _CACHE["v"] is not None and time.time() - _CACHE["t"] < TTL:
        return _CACHE["v"]
    try:
        v = _from_github(repo)
    except Exception:
        v = _CACHE["v"] or {"version_code": 0, "version_name": "", "apk_url": None, "notes": ""}
    _CACHE.update(t=time.time(), v=v)
    return v


@router.get("/version")
def version():
    return _latest()
