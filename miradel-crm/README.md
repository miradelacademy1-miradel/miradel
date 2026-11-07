# Miradel CRM — 1-6 bosqich (…, chat, Android APK)

FastAPI + PostgreSQL. Frontend — oddiy HTML (`static/`).

## Nima bor
- `/admin/` — admin sayti (kompyuter + telefon): oʻquvchi qoʻshish va login kartochkasini chop etish, xodim qoʻshish (menejer / oʻqituvchi / ikkalasi), guruhlar.
- `/app/` — oʻquvchi ilovasi (PWA): bosh sahifa, topshiriqlar, reyting tablosi, artifaktlar, profil. Oflayn ishlaydi. Oʻqituvchi/menejer ekranlari 3-4 bosqichda.
- `/api/...` — kirish (`/api/auth/*`) va admin API (`/api/admin/*`), hujjat: `/docs`.

## Oflayn sinxronlash (2-bosqich)
- `GET /api/sync/pull` — oʻquvchining toʻliq snapshoti (topshiriq, eʼlon, artifakt, ball, reyting). Ilova uni IndexedDB’da saqlaydi va internetsiz ochadi.
- `POST /api/sync/push` — oflaynda bajarilgan topshiriqlar navbati. Har bir harakatda noyob `uid` bor, shuning uchun qayta yuborilsa ikki marta hisoblanmaydi.
- Ilova ochilganda, internet qaytganda va har 60 soniyada avtomatik sinxronlanadi.
- Aktivlik % = oxirgi 30 kundagi ball / oylik maqsad (admin “Topshiriqlar” boʻlimida belgilaydi).
- Admin: topshiriq (kunlik/haftalik/oylik/artifakt/dars materiali), eʼlon, artifakt, guruh dars jadvali (kunlar + vaqt).
- Eski baza yangilanishi: ishga tushganda yangi jadval va ustunlar avtomatik qoʻshiladi (maʼlumot oʻchmaydi). Qoʻlda migratsiya kerak emas.

## Oʻqituvchi ilovasi (3-bosqich) — `/app/teacher.html`
- Kirishdan keyin oʻqituvchi avtomatik shu sahifaga oʻtadi. Menejer+oʻqituvchi boʻlsa tepada “Menejer ›” tugmasi chiqadi (menejer ekranlari 4-bosqichda).
- Davomat (Keldi / Kelmadi / Sababli, oxirgi 14 kun), topshiriq berish, guruhga xabar yuborish, dars hisoboti.
- Hammasi oflayn navbat bilan ishlaydi: `GET /api/teacher/pull`, `POST /api/teacher/push` (har harakatda noyob `uid`, takror yuborilsa ikki marta yozilmaydi).
- Oʻqituvchi faqat oʻziga biriktirilgan guruhlar bilan ishlay oladi (server tekshiradi).
- “Keldi” belgilansa oʻquvchiga davomat balli yoziladi (admin “Topshiriqlar” boʻlimida belgilaydi, standart 2). Belgi oʻzgarsa ball ham toʻgʻrilanadi.
- Oʻquvchi profilida “Davomat (oxirgi 30 kun)” koʻrinadi.

## Menejer ilovasi (4-bosqich) — `/app/manager.html`
- **Moliya:** oy boʻyicha oʻquvchi toʻlovlari (Toʻlangan / Qisman / Kutilmoqda / Qarz), tushum va kutilgan summa, qarzdorlar, toʻlov qabul qilish (naqd/karta/oʻtkazma), xato toʻlovni bekor qilish (oʻchirilmaydi, “bekor qilingan” boʻlib qoladi, audit_log’ga yoziladi).
- **Narx:** guruh narxi + oʻquvchiga individual narx (chegirma) va toʻlov kuni. Individual narx 0 boʻlsa guruh narxi ishlatiladi.
- **Maosh:** har bir oʻqituvchiga usul: `Dars soni × stavka` (dars = oʻqituvchi yuborgan dars hisoboti, guruh+kun boʻyicha 1 ta), `Tushumdan foiz` (oʻqituvchi guruhlarining shu oy tushumidan) yoki `Qatʼiy oylik`. Toʻlangan summa va qoldiq hisoblanadi.
- **Ish rejasi:** menejer oʻqituvchiga vazifa belgilaydi; oʻqituvchi ilovasidagi “Reja” boʻlimida koʻradi va bajarildi deb belgilaydi (oflayn ishlaydi).
- **Hisobot:** oʻqituvchilarning dars hisobotlari.
- Pul bilan bogʻliq amallar ataylab faqat onlayn ishlaydi (oflayn navbat yoʻq), ikki marta yozilib ketmasligi uchun.
- Oʻquvchi profilida oʻz toʻlov holati va keyingi toʻlov sanasi koʻrinadi, muddat yaqinlashsa bosh sahifada eslatma chiqadi.
- Menejer+oʻqituvchi bitta login bilan kiradi, tepadagi tugma bilan panellar almashadi. Admin ham `/app/manager.html` ga kira oladi (admin paneldagi “Menejer paneli” havolasi).

## Chat (5-bosqich)
- Ikki turdagi suhbat: **guruh chati** (guruh oʻquvchilari + guruh oʻqituvchisi) va **shaxsiy** (oʻquvchi ↔ oʻz guruhi oʻqituvchisi). Oʻquvchilar bir-biriga shaxsiy yoza olmaydi; boshqa guruh chatiga kira olmaydi (server tekshiradi).
- Umumiy modul: `static/app/chat.js` (oʻquvchi va oʻqituvchi ilovalari ishlatadi). Polling 4 soniya, WebSocket kerak emas.
- Oʻqilmagan xabar belgisi menyuda, oflayn yozilgan xabarlar navbatda turadi va internet kelganda yuboriladi (takrorlanmaydi), oxirgi xabarlar oflayn koʻrinadi.
- Spamdan himoya: bir foydalanuvchi daqiqasiga 30 tagacha xabar.
- Admin “Chat nazorati” boʻlimida barcha suhbatni koʻradi va nomaqbul xabarni oʻchiradi (xabar “Xabar oʻchirilgan” boʻlib qoladi, audit_log’ga yoziladi).
- Chiqishda (logout) telefondagi barcha mahalliy maʼlumot (chat tarixi ham) tozalanadi.

## Android APK (6-bosqich, 1-qism)
- `mobile/` — Capacitor oʻrami, `.github/workflows/` — APK ni GitHub oʻzi yigʻadigan 2 ta workflow (kalit yaratish + APK yigʻish). Toʻliq yoʻriqnoma: **`mobile/README.md`**.
- `/download/` — oʻquvchilar uchun yuklab olish sahifasi (oʻrnatish yoʻriqnomasi bilan). `/api/app/version` — eng yangi APK versiyasi (GITHUB_REPO yoki APK_URL + APK_VERSION muhit oʻzgaruvchilari).
- APK ichida ilova fayllari bundled (oflayn ochiladi), API manzili `config.js` dagi `API_BASE` dan olinadi. Server CORS: `CORS_ORIGINS` (standart: `https://localhost,capacitor://localhost,http://localhost`).
- Yangi versiya chiqsa, APK ichidagi ilova tepada “Yuklab olish” eslatmasini koʻrsatadi.

## Rollar
Bitta foydalanuvchida bayroqlar: `is_student`, `is_teacher`, `is_manager`, `is_admin`.
Menejer+oʻqituvchi bitta login bilan kiradi (`panels` ichida ikkalasi qaytadi).

## Railway’ga joylash
1. GitHub’ga yuklang, Railway’da *New Project → Deploy from GitHub*.
2. *Add → Database → PostgreSQL* (DATABASE_URL avtomatik ulanadi).
3. Variables: `SECRET_KEY`, `ENV=prod`, `ADMIN_LOGIN`, `ADMIN_PASSWORD` (`.env.example` ga qarang).
4. Deploy tugagach `https://<domen>/admin/` ga admin sifatida kiring.
Birinchi ishga tushishda jadvallar va admin avtomatik yaratiladi.

## Mahalliy ishga tushirish
```
pip install -r requirements.txt
ADMIN_PASSWORD=test1234 uvicorn app.main:app --reload
```
(DATABASE_URL berilmasa SQLite `dev.db` ishlatiladi.)

## Eslatmalar
- Login: oʻquvchilar `miradel-0002`, xodimlar `xodim-003` koʻrinishida (admin xohlasa xodimga oʻz loginini beradi).
- Parol faqat yaratilganda yoki yangilanganda bir marta koʻrsatiladi.
- 5 ta notoʻgʻri urinishdan keyin 5 daqiqa bloklanadi (hozircha xotirada; 2-bosqichda bazaga koʻchiriladi).
- Jadvallar `create_all` bilan yaratiladi; sxema 2-bosqichda barqarorlashgach Alembic’ga oʻtiladi.
