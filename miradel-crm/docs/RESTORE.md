# Miradel CRM — Ma'lumotlarni tiklash qo'llanmasi

Ushbu hujjat ma'lumotlar bazasini zaxiralash va tiklash bo'yicha ko'rsatmalarni o'z ichiga oladi.

## 1. Railway PostgreSQL zaxira nusxalari

Railway har kuni avtomatik ravishda ma'lumotlar bazasini zaxiralaydi (agar loyihada yoqilgan bo'lsa).
- **Tekshirish:** Railway Dashboard -> PostgreSQL Service -> "Backups" tab.
- **Tiklash:** Zaxira nusxasini tanlab, "Restore" tugmasini bosing. Bu joriy bazani o'chirib, zaxiraga almashtiradi.

## 2. CSV eksport (Zaxira nusxa yuklab olish)

Admin panel -> Sozlamalar bo'limida "Zaxira nusxa yuklab olish" tugmasi mavjud.
Ushbu tugma quyidagi fayllarni o'z ichiga olgan ZIP arxivni yuklab oladi:
- `users.csv`, `groups.csv`, `attendance.csv`, `payments.csv`, `tasks.csv`, va hokazo.
- `manifest.json` — har bir jadvaldagi yozuvlar soni.

**Muhim:**
- Ushbu CSV fayllar **to'liq tiklash** uchun mo'ljallanmagan. Ular asosan hisobot va tahlil uchun.
- ZIP fayl shaxsiy ma'lumotlarni o'z ichiga oladi, shuning uchun uni xavfsiz joyda saqlang.

## 3. Tavsiya etilgan tartib

1. Har hafta Admin paneldan ZIP zaxira nusxasini yuklab oling.
2. Kamida 4 ta nusxani serverdan tashqarida saqlang (masalan, Google Drive, tashqi disk).
3. Har oyda Railway PostgreSQL zaxirasini tekshiring va kerak bo'lsa qo'lda tiklashni sinab ko'ring.
