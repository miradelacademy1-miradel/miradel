# Miradel Android ilovasi (APK)

APK ni **GitHub oʻzi yigʻadi** (kompyuteringizga hech narsa oʻrnatish shart emas). Ilova — `static/app` dagi veb ilovaning Capacitor oʻrami: fayllar APK ichida turadi (shuning uchun oflayn ochiladi), maʼlumot Railway serveridan olinadi.

## Bir martalik sozlash
1. Repo **public** boʻlsin (kodda parol yoʻq; maxfiy qiymatlar Railway va GitHub Secrets da). Public boʻlsa APK havolasi hammaga ochiq boʻladi va ilova yangilanishni oʻzi bilib oladi.
2. GitHub → repo → **Settings → Secrets and variables → Actions → Variables** → `API_BASE` = `https://sizning-domen.up.railway.app` (oxirida `/` yoʻq).
3. **Actions → “1) APK imzo kaliti yaratish” → Run workflow.** Tugagach ishga tushirish sahifasidan `keystore-yashirin` artifactni yuklab oling, ichidagi `kalit-malumotlari.txt` dagi 4 qiymatni **Secrets** ga yozing: `ANDROID_KEYSTORE_B64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`. Keyin artifactni oʻchiring. `miradel.jks` faylini xavfsiz joyga **zaxiralang** (yoʻqotsangiz, ilovani yangilab boʻlmaydi).
4. Railway → Variables: `GITHUB_REPO` = `egasi/repo-nomi` (APK versiyasini server shu yerdan biladi).

## APK chiqarish (har safar)
**Actions → “2) Android APK yigʻish” → Run workflow.** ~5-8 daqiqada **Releases** boʻlimida `miradel.apk` paydo boʻladi. Oʻquvchilarga `https://sizning-domen.up.railway.app/download/` havolasini bering.

- Kalit Secrets da boʻlmasa, faqat `miradel-test.apk` (sinov) yigʻiladi va “prerelease” boʻladi. Sinov APK ni keyin rasmiy APK bilan yangilab boʻlmaydi, avval oʻchirib qayta oʻrnatish kerak.
- Oʻquvchilar ilovani ochganda yangi versiya chiqqan boʻlsa, tepada “Yuklab olish” eslatmasi chiqadi.

## Qachon yangi APK kerak?
Ilovaning ekranlari (HTML) APK ichida turadi. `static/app` ichidagi fayllarni oʻzgartirsangiz (dizayn, yangi ekran), yangi APK yigʻish kerak. Serverdagi maʼlumot va qoidalar (topshiriqlar, ballar, toʻlovlar) esa APK’siz yangilanadi.

## Mahalliy tekshirish (ixtiyoriy)
```
cd mobile && npm install
API_BASE=https://sizning-domen.up.railway.app APP_VERSION=1 node scripts/build-web.js
```
