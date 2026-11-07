/* APK ichida ishlaganda yangi versiya chiqqanini tekshiradi (internet boʻlsa) va tepada eslatma koʻrsatadi. */
(function () {
  if (!window.APP_VERSION || !navigator.onLine) return;
  var seen = sessionStorage.getItem("upd-seen");
  if (seen) return; sessionStorage.setItem("upd-seen", "1");
  fetch((window.API_BASE || "") + "/api/app/version").then(function (r) { return r.json(); }).then(function (v) {
    if (!v || !v.apk_url || !(v.version_code > window.APP_VERSION)) return;
    var b = document.createElement("div");
    b.setAttribute("role", "status");
    b.style.cssText = "position:fixed;left:12px;right:12px;top:calc(8px + env(safe-area-inset-top,0px));z-index:50;background:#2b2e33;color:#f1f2f2;border-radius:14px;padding:10px 14px;display:flex;gap:10px;align-items:center;font:14px system-ui,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.3)";
    var t = document.createElement("span"); t.style.flex = "1"; t.textContent = "Ilovaning yangi versiyasi bor";
    var a = document.createElement("a"); a.textContent = "Yuklab olish"; a.href = v.apk_url; a.target = "_blank"; a.rel = "noopener";
    a.style.cssText = "color:#fff;font-weight:700;text-decoration:underline";
    var x = document.createElement("button"); x.textContent = "✕"; x.setAttribute("aria-label", "Yopish"); x.style.cssText = "background:none;border:0;color:#f1f2f2;font-size:16px;cursor:pointer";
    x.onclick = function () { b.remove(); };
    b.appendChild(t); b.appendChild(a); b.appendChild(x); document.body.appendChild(b);
  }).catch(function () {});
})();
