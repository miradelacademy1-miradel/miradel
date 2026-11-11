(function(){
  var $ = function(s){ return document.querySelector(s); };
  function esc(s){ var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  var T = localStorage.getItem("pt") || "";
  var U = null;
  try { U = JSON.parse(localStorage.getItem("pu") || "null"); } catch(e) {}

  function toast(t){ var e = $("#toast"); e.textContent = t; e.classList.add("on"); clearTimeout(toast._x); toast._x = setTimeout(function(){ e.classList.remove("on"); }, 2600); }

  function api(path, o){
    o = o || {};
    var h = { "Content-Type": "application/json" };
    if (T) h.Authorization = "Bearer " + T;
    return fetch(path, { method: o.method || "GET", headers: h, body: o.body ? JSON.stringify(o.body) : undefined })
      .then(function(r){
        return r.json().catch(function(){ return null; }).then(function(d){
          if (r.status === 401) { logout(); throw new Error("Sessiya tugadi"); }
          if (!r.ok) {
            var msg = (d && typeof d.detail === "string") ? d.detail : "Xatolik (" + r.status + ")";
            throw new Error(msg);
          }
          return d;
        });
      });
  }

  function fmtMoney(n){ return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " soʻm"; }
  function month(){ var d = new Date(); return d.getFullYear() + "-" + (d.getMonth() < 9 ? "0" : "") + (d.getMonth() + 1); }

  var pages = [];
  function register(p){ pages.push(p); }

  function renderTabs(){
    var box = $("#tabs"); box.innerHTML = "";
    pages.forEach(function(p){
      var b = document.createElement("button");
      b.textContent = p.icon + " " + p.title;
      b.dataset.id = p.id;
      b.onclick = function(){ location.hash = "#" + p.id; };
      box.appendChild(b);
    });
  }

  function route(){
    if (!U) { showLogin(); return; }
    var id = (location.hash || "#home").slice(1).split("?")[0];
    var p = pages.filter(function(x){ return x.id === id; })[0] || pages[0];
    document.querySelectorAll("#tabs button").forEach(function(b){ b.classList.toggle("on", b.dataset.id === p.id); });
    $("#who-name").textContent = U.full_name || "";
    $("#who-role").textContent = U.is_admin ? "Admin" : (U.is_manager ? "Menejer" : "");
    var main = $("#main"); main.innerHTML = "";
    try { p.render(main, { api: api, esc: esc, toast: toast, fmtMoney: fmtMoney, month: month, user: U }); }
    catch(e){ main.innerHTML = '<div class="card" style="color:var(--bad)">' + esc(e.message || "Xatolik") + '</div>'; }
  }

  function showLogin(){
    $("#login").hidden = false;
    $("#shell").hidden = true;
  }
  function showShell(){
    $("#login").hidden = true;
    $("#shell").hidden = false;
    renderTabs(); route();
  }

  function logout(){
    T = ""; U = null;
    localStorage.removeItem("pt"); localStorage.removeItem("pu");
    showLogin();
  }

  $("#go").onclick = function(){
    $("#lg-err").textContent = "";
    var lg = $("#lg").value, pw = $("#pw").value;
    if (!lg || !pw) { $("#lg-err").textContent = "Login va parolni kiriting"; return; }
    fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ login: lg, password: pw }) })
      .then(function(r){ return r.json().then(function(d){ return { s: r.status, d: d }; }); })
      .then(function(x){
        if (x.s !== 200) { $("#lg-err").textContent = (x.d && typeof x.d.detail === "string") ? x.d.detail : "Kirish amalga oshmadi"; return; }
        var u = x.d.user;
        if (!u.is_manager && !u.is_admin) { $("#lg-err").textContent = "Bu panel menejer va adminlar uchun"; return; }
        T = x.d.token; U = u;
        localStorage.setItem("pt", T);
        localStorage.setItem("pu", JSON.stringify(U));
        showShell();
      }).catch(function(){ $("#lg-err").textContent = "Serverga ulanmadi"; });
  };
  $("#pw").onkeydown = function(e){ if (e.key === "Enter") $("#go").click(); };
  $("#out").onclick = logout;
  window.addEventListener("hashchange", route);

  window.Panel = { register: register, api: api, esc: esc, toast: toast, fmtMoney: fmtMoney, month: month, go: route };

  // Boot: only after all pages are registered
  window.addEventListener("load", function(){
    if (T && U && (U.is_manager || U.is_admin)) {
      showShell();
    } else {
      T = ""; U = null; localStorage.removeItem("pt"); localStorage.removeItem("pu");
      showLogin();
    }
  });
})();
