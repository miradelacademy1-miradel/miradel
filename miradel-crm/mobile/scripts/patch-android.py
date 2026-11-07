"""`npx cap add android` dan keyin: versiya, ikonka va xavfsizlik sozlamalarini qoʻyadi.
Ishlatish (mobile/ ichidan): VERSION_CODE=12 python3 scripts/patch-android.py"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANDROID = os.path.join(ROOT, "android")
code = int(os.environ.get("VERSION_CODE", "1") or 1)

# 1) versionCode / versionName
gp = os.path.join(ANDROID, "app", "build.gradle")
s = open(gp, encoding="utf-8").read()
s, n1 = re.subn(r"versionCode\s+\d+", f"versionCode {code}", s, count=1)
s, n2 = re.subn(r'versionName\s+"[^"]*"', f'versionName "1.0.{code}"', s, count=1)
if not (n1 and n2):
    sys.exit("XATO: build.gradle da versionCode/versionName topilmadi")
open(gp, "w", encoding="utf-8").write(s)

# 2) zaxira nusxa olishni oʻchirish (login maʼlumoti telefon zaxirasiga tushmasin)
mp = os.path.join(ANDROID, "app", "src", "main", "AndroidManifest.xml")
m = open(mp, encoding="utf-8").read()
if "android:allowBackup=" in m:
    m = re.sub(r'android:allowBackup="[^"]*"', 'android:allowBackup="false"', m, count=1)
else:
    m = m.replace("<application", '<application android:allowBackup="false"', 1)
open(mp, "w", encoding="utf-8").write(m)

# 3) ikonka: moslashuvchan (adaptive) ikonkani oʻchirib, oddiy PNG ikonka qoʻyamiz
res = os.path.join(ANDROID, "app", "src", "main", "res")
shutil.rmtree(os.path.join(res, "mipmap-anydpi-v26"), ignore_errors=True)
try:
    from PIL import Image
    icon = Image.open(os.path.join(ROOT, "..", "static", "app", "icons", "icon-512.png")).convert("RGBA")
    for d, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        folder = os.path.join(res, f"mipmap-{d}")
        os.makedirs(folder, exist_ok=True)
        for name in ("ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"):
            icon.resize((px, px), Image.LANCZOS).save(os.path.join(folder, name))
except Exception as e:  # ikonka almashmasa ham APK yigʻiladi
    print("OGOHLANTIRISH: ikonka almashtirilmadi:", e)
print("android loyiha moslandi: versionCode", code)
