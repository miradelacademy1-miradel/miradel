// static/app ichidagi fayllarni mobile/www ga koʻchiradi va config.js ni APK uchun yozadi.
// Ishlatish: API_BASE=https://sizning-domen.up.railway.app APP_VERSION=12 node scripts/build-web.js
const fs = require("fs");
const path = require("path");

const src = path.join(__dirname, "..", "..", "static", "app");
const dst = path.join(__dirname, "..", "www");
const base = (process.env.API_BASE || "").trim().replace(/\/+$/, "");
const ver = parseInt(process.env.APP_VERSION || "1", 10) || 1;

if (!/^https:\/\/[^\s/]+$/.test(base)) {
  console.error("XATO: API_BASE https://domen koʻrinishida boʻlishi kerak (oxirida / yoʻq). Hozir: '" + base + "'");
  process.exit(1);
}

fs.rmSync(dst, { recursive: true, force: true });
fs.mkdirSync(dst, { recursive: true });
(function copy(from, to) {
  for (const e of fs.readdirSync(from, { withFileTypes: true })) {
    const a = path.join(from, e.name), b = path.join(to, e.name);
    if (e.isDirectory()) { fs.mkdirSync(b, { recursive: true }); copy(a, b); }
    else if (e.name !== "sw.js") fs.copyFileSync(a, b); // APK ichida service worker kerak emas, fayllar ichiga joylangan
  }
})(src, dst);

fs.writeFileSync(path.join(dst, "config.js"),
  "window.API_BASE = " + JSON.stringify(base) + ";\nwindow.APP_VERSION = " + ver + ";\n");
console.log("www tayyor. API_BASE=" + base + " APP_VERSION=" + ver);
