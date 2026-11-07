/* Miradel chat: oʻquvchi va oʻqituvchi ilovalari uchun umumiy modul.
   Polling (4 soniya) bilan ishlaydi; oflaynda yozilgan xabarlar navbatda turadi va internet kelganda yuboriladi. */
(function () {
  var css = ".cv{display:flex;flex-direction:column;min-height:calc(100vh - 210px)}.ch{display:flex;align-items:center;gap:10px;padding:6px 0 10px}.ch b{display:block}.ch small{color:var(--mute);font-size:12px}" +
    ".cb{width:36px;height:36px;border-radius:50%;background:var(--card);font-size:22px;line-height:1;flex:none}.cm{flex:1;display:flex;flex-direction:column;gap:6px;padding:4px 0 10px}" +
    ".bub{max-width:82%;padding:8px 12px;border-radius:16px;background:var(--card);align-self:flex-start;word-break:break-word;white-space:pre-wrap}.bub.me{align-self:flex-end;background:var(--acc);color:var(--accink)}" +
    ".bub small{display:block;font-size:11px;opacity:.65;white-space:normal}.bub.pd{opacity:.6}.bub.dl{font-style:italic;opacity:.6}" +
    ".cs{position:sticky;bottom:0;display:flex;gap:8px;padding:8px 0;background:var(--bg)}.cs textarea{flex:1;resize:none;border:1.5px solid var(--line);background:var(--card);color:var(--ink);border-radius:18px;padding:10px 14px;font:inherit;max-height:96px}" +
    ".cs button{background:var(--acc);color:var(--accink);border-radius:18px;padding:0 16px;font-weight:600}" +
    ".ct{display:flex;gap:10px;align-items:center;width:100%;text-align:left;padding:10px 0;border-bottom:1px solid var(--line)}.ct:last-child{border:0}" +
    ".ct .av{width:40px;height:40px;border-radius:50%;background:var(--line);display:grid;place-items:center;font-weight:700;font-size:13px;flex:none}" +
    ".ct .nm{flex:1;min-width:0}.ct .nm small{display:block;color:var(--mute);font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ct .tm{font-size:11.5px;color:var(--mute);text-align:right}" +
    ".ubd{background:var(--bad);color:#fff;border-radius:10px;min-width:18px;padding:0 5px;font-size:11px;font-weight:700;display:inline-block;text-align:center;margin-top:3px}" +
    ".csearch{width:100%;margin-bottom:8px;border:1.5px solid var(--line);background:var(--card);color:var(--ink);border-radius:14px;padding:10px 12px;font:inherit}.csec{margin:12px 2px 4px;font-size:13px;font-weight:600;color:var(--mute)}" +
    "nav button{position:relative}.bdg{position:absolute;top:2px;right:12px;background:var(--bad);color:#fff;border-radius:9px;min-width:16px;height:16px;font-size:10px;font-weight:700;line-height:16px;font-style:normal;padding:0 4px;text-align:center}.bdg[hidden]{display:none}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  var O = null, root, threads = [], cur = null, msgs = [], lastId = 0, pend = [], act = false, flushing = false, q = "", busy = false;
  function $(s) { return root.querySelector(s); }
  function esc(s) { return O.esc(s); }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 10); }
  function tm(iso) {
    if (!iso) return ""; var d = new Date(iso), n = new Date(), p = function (x) { return (x < 10 ? "0" : "") + x; };
    return d.toDateString() === n.toDateString() ? p(d.getHours()) + ":" + p(d.getMinutes()) : p(d.getDate()) + "." + p(d.getMonth() + 1);
  }
  function ini(s) { return (s || "?").split(" ").map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase(); }
  function persist() { return O.kvSet("c_queue", pend); }

  // ---- belgi (oʻqilmagan) ----
  function badge(n) {
    var b = O.badgeBtn; if (!b) return; var i = b.querySelector(".bdg");
    if (!i) { i = document.createElement("i"); i.className = "bdg"; b.appendChild(i); }
    i.hidden = !n; i.textContent = n > 9 ? "9+" : n;
  }
  function unread() {
    if (!navigator.onLine) return Promise.resolve();
    return O.api("/chat/unread").then(function (r) { badge(act && cur ? 0 : r.count); }).catch(function () {});
  }

  // ---- suhbatlar roʻyxati ----
  function renderList() {
    if (!threads.length) { root.innerHTML = '<div class="empty" style="margin-top:14px">Hozircha suhbat yoʻq. Guruhga biriktirilganingizdan keyin chat shu yerda chiqadi.</div>'; return; }
    var ql = q.toLowerCase(), g = [], d = [];
    threads.forEach(function (t) { if (ql && (t.title + " " + t.subtitle).toLowerCase().indexOf(ql) < 0) return; (t.kind === "group" ? g : d).push(t); });
    function row(t) {
      return '<button class="ct" data-k="' + esc(t.key) + '"><span class="av">' + esc(ini(t.title)) + '</span><span class="nm"><b>' + esc(t.title) + "</b><small>" + esc(t.last || t.subtitle) + '</small></span><span class="tm">' + tm(t.last_at) + (t.unread ? '<br><span class="ubd">' + t.unread + "</span>" : "") + "</span></button>";
    }
    var h = threads.length > 8 ? '<input class="csearch" id="csq" placeholder="Qidirish" value="' + esc(q) + '" aria-label="Qidirish">' : "";
    if (g.length) h += '<div class="csec">Guruh chati</div><div class="card">' + g.map(row).join("") + "</div>";
    if (d.length) h += '<div class="csec">' + (O.role === "teacher" ? "Oʻquvchilar bilan" : "Oʻqituvchi bilan") + '</div><div class="card">' + d.map(row).join("") + "</div>";
    if (!g.length && !d.length) h += '<div class="empty">Topilmadi</div>';
    root.innerHTML = h;
    var s = $("#csq"); if (s) { s.oninput = function () { q = s.value; var p = s.selectionStart; renderList(); var s2 = $("#csq"); s2.focus(); s2.setSelectionRange(p, p); }; }
    Array.prototype.forEach.call(root.querySelectorAll(".ct"), function (b) { b.onclick = function () { open(threads.filter(function (t) { return t.key === b.dataset.k; })[0]); }; });
  }
  function refreshThreads() {
    if (busy) return Promise.resolve(); busy = true;
    return O.api("/chat/threads").then(function (t) {
      threads = t; O.kvSet("c_threads", t); if (!cur) renderList();
      badge(t.reduce(function (a, x) { return a + (x.unread || 0); }, 0));
    }).catch(function () {}).then(function () { busy = false; });
  }

  // ---- suhbat ----
  function open(t) {
    if (!t) return; cur = t; msgs = []; lastId = 0; badge(0);
    root.innerHTML = '<div class="cv"><div class="ch"><button class="cb" id="cbk" aria-label="Orqaga">‹</button><div><b>' + esc(t.title) + "</b><small>" + esc(t.subtitle) + '</small></div></div><div class="cm" id="cm"></div><div class="cs"><textarea id="cin" rows="1" maxlength="1000" placeholder="Xabar yozing" aria-label="Xabar"></textarea><button id="csd">Yuborish</button></div></div>';
    $("#cbk").onclick = back; $("#csd").onclick = send;
    $("#cin").onkeydown = function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
    $("#cin").oninput = function () { this.style.height = "auto"; this.style.height = Math.min(this.scrollHeight, 96) + "px"; };
    var key = t.key;
    O.kvGet("c_msgs:" + key).then(function (c) { if (cur && cur.key === key && c && !msgs.length) { msgs = c; lastId = msgs.length ? msgs[msgs.length - 1].id : 0; draw(true); } }).then(function () { return fetchNew(true); });
    draw(true);
  }
  function back() { cur = null; msgs = []; renderList(); refreshThreads(); }
  function merge(arr) {
    var have = {}; msgs.forEach(function (m) { have[m.id] = 1; });
    arr.forEach(function (m) { if (!have[m.id]) { msgs.push(m); have[m.id] = 1; } });
    msgs.sort(function (a, b) { return a.id - b.id; }); lastId = msgs.length ? msgs[msgs.length - 1].id : 0;
    if (msgs.length > 100) msgs = msgs.slice(-100);
  }
  function fetchNew(first) {
    if (!cur || !navigator.onLine) return Promise.resolve(); var key = cur.key, after = lastId;
    return O.api("/chat/messages?key=" + encodeURIComponent(key) + (after ? "&after_id=" + after : "")).then(function (r) {
      if (!cur || cur.key !== key) return;
      var had = msgs.length; merge(r.messages); O.kvSet("c_msgs:" + key, msgs);
      if (first || msgs.length !== had) draw(first);
    }).catch(function () {});
  }
  function draw(forceBottom) {
    var box = $("#cm"); if (!box || !cur) return; var near = box.parentNode && (window.innerHeight + (root.closest("main") || document.body).scrollTop >= (root.closest("main") || document.body).scrollHeight - 140);
    var grp = cur.kind === "group", h = "";
    msgs.forEach(function (m) {
      var me = m.sender_id === O.meId;
      h += '<div class="bub' + (me ? " me" : "") + (m.deleted ? " dl" : "") + '">' + (!me && grp ? "<small>" + esc(m.sender_name) + (m.sender_role === "teacher" ? " · oʻqituvchi" : "") + "</small>" : "") + esc(m.body) + "<small>" + tm(m.at) + "</small></div>";
    });
    pend.filter(function (p) { return p.key === cur.key; }).forEach(function (p) { h += '<div class="bub me pd">' + esc(p.body) + "<small>yuborilmoqda…</small></div>"; });
    box.innerHTML = h || '<div class="empty">Hali xabar yoʻq. Birinchi boʻlib yozing.</div>';
    if (forceBottom || near) { var sc = root.closest("main") || document.body; sc.scrollTop = sc.scrollHeight; }
  }
  function send() {
    var ta = $("#cin"); if (!ta || !cur) return; var body = ta.value.trim(); if (!body) return;
    pend.push({ uid: uid(), key: cur.key, body: body }); persist(); ta.value = ""; ta.style.height = "auto"; draw(true); flush();
  }
  function flush() {
    if (flushing || !navigator.onLine || !pend.length) return Promise.resolve(); flushing = true;
    function next() {
      if (!pend.length) return Promise.resolve(); var p = pend[0];
      return O.api("/chat/send", { method: "POST", body: { key: p.key, body: p.body, uid: p.uid } }).then(function (r) {
        pend.shift(); persist(); if (cur && cur.key === p.key) { merge([r.message]); O.kvSet("c_msgs:" + p.key, msgs); } draw(true); return next();
      }, function (e) {
        if (e.offline || e.status === 429) { if (e.status === 429) O.toast(e.message); return; }
        pend.shift(); persist(); O.toast(e.message || "Xabar yuborilmadi"); draw(); return next();
      });
    }
    return next().then(function () { flushing = false; }, function () { flushing = false; });
  }

  // ---- umumiy ----
  function tick() {
    if (!act || document.hidden || !navigator.onLine) return;
    if (cur) fetchNew().then(flush); else { flush(); refreshThreads(); }
  }
  window.MiradelChat = {
    init: function (o) {
      O = o; root = o.root;
      Promise.all([o.kvGet("c_queue"), o.kvGet("c_threads")]).then(function (r) { pend = r[0] || []; threads = r[1] || threads; if (act && !cur) renderList(); flush(); });
      setInterval(tick, 4000); setInterval(function () { if (!document.hidden && !(act && cur)) unread(); }, 30000);
      window.addEventListener("online", function () { flush(); unread(); });
      unread();
    },
    active: function (v) {
      act = !!v; if (!O || !v) return;
      if (cur) { draw(true); fetchNew().then(flush); badge(0); } else { renderList(); refreshThreads(); flush(); }
    },
    reset: function () { pend = []; threads = []; cur = null; }
  };
})();
