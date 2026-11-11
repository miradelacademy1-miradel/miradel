(function(){
  var P = window.Panel;

  function subTabs(ctx, container, active, onChange){
    var tabs = [
      { id: "daily", label: "Kunlik" },
      { id: "matrix", label: "Oylik jadval" },
      { id: "absent", label: "Yoʻqlar" },
      { id: "calendar", label: "Kalendar" },
      { id: "suspicious", label: "Shubhali" },
    ];
    var bar = document.createElement("div");
    bar.className = "tabs";
    tabs.forEach(function(t){
      var b = document.createElement("button");
      b.textContent = t.label;
      if (t.id === active) b.classList.add("on");
      b.onclick = function(){ onChange(t.id); };
      bar.appendChild(b);
    });
    container.appendChild(bar);
    return bar;
  }

  function today(){ var d = new Date(); return d.getFullYear() + "-" + (d.getMonth() < 9 ? "0" : "") + (d.getMonth() + 1) + "-" + (d.getDate() < 10 ? "0" : "") + d.getDate(); }

  // ---------------- Daily tab ----------------
  function renderDaily(container, ctx, state){
    var wrap = document.createElement("div");
    wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
    container.appendChild(wrap);
    var day = state.day || today();

    function reload(){
      wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
      ctx.api("/api/attendance/day?day=" + day).then(function(d){
        var groupsHtml = d.groups.map(function(g, i){
          var stateChip = {
            "marked": '<span class="chip c-ok">Belgilangan</span>',
            "missing": '<span class="chip c-bad">Belgilanmagan</span>',
            "holiday": '<span class="chip c-mute">Dam olish</span>',
            "cancelled": '<span class="chip c-warn">Bekor</span>',
            "not_scheduled": '<span class="chip c-mute">Jadvalda yoʻq</span>',
          }[g.state] || "";
          var flags = "";
          if (g.off_schedule) flags += ' <span class="flag">🔶 jadvalda yoʻq</span>';
          if (g.all_present) flags += ' <span class="flag">100% keldi</span>';
          var stuRows = g.students.map(function(s){
            var opts = [
              { v: "present", l: "Keldi" },
              { v: "absent", l: "Kelmadi" },
              { v: "excused", l: "Sababli" },
              { v: "", l: "Belgilanmagan" },
            ].map(function(o){ return '<option value="' + o.v + '"' + (s.status === o.v || (!s.status && !o.v) ? " selected" : "") + '>' + o.l + '</option>'; }).join("");
            return '<div class="stu-row" data-sid="' + s.id + '"><span>' + ctx.esc(s.full_name) + '</span><select class="stu-status">' + opts + '</select></div>';
          }).join("");
          return '<details data-gid="' + g.group_id + '" data-state="' + g.state + '">' +
            '<summary>' + ctx.esc(g.group) + ' · ' + stateChip + ' ' + flags + '</summary>' +
            '<div class="sub" style="margin:8px 0">Oʻqituvchi: ' + ctx.esc(g.effective_teacher || "—") + ' · ' +
              'Keldi: ' + g.counts.present + ' · Kelmadi: ' + g.counts.absent + ' · Sababli: ' + g.counts.excused + ' · Belgilanmagan: ' + g.counts.unmarked + '</div>' +
            '<div class="stu-list">' + stuRows + '</div>' +
            '<div style="display:flex;gap:8px;margin-top:10px">' +
              '<input class="reason" placeholder="Sabab (oʻzgartirish uchun majburiy)" style="flex:1">' +
              '<button class="btn g save-group">Saqlash</button>' +
            '</div>' +
          '</details>';
        }).join("") || '<div class="sub">Guruhlar yoʻq</div>';

        wrap.innerHTML = '' +
          '<div class="card">' +
            '<div class="row" style="margin-bottom:0">' +
              '<label>Sana<input type="date" id="daily-day" value="' + day + '"></label>' +
              '<label style="flex:0;min-width:0"><span></span><button class="btn g" id="daily-reload">Yangilash</button></label>' +
              '<label style="flex:0;min-width:0"><span></span><button class="btn g" id="daily-only-missing">Faqat belgilanmaganlar</button></label>' +
            '</div>' +
          '</div>' +
          '<div class="card" id="daily-groups">' + groupsHtml + '</div>';

        document.getElementById("daily-day").onchange = function(e){ day = e.target.value; state.day = day; reload(); };
        document.getElementById("daily-reload").onclick = reload;
        document.getElementById("daily-only-missing").onclick = function(e){
          var on = e.target.classList.toggle("on");
          document.querySelectorAll("#daily-groups details").forEach(function(d){
            d.style.display = (!on || d.dataset.state === "missing") ? "" : "none";
          });
        };

        document.querySelectorAll("#daily-groups details").forEach(function(det){
          var gid = +det.dataset.gid;
          det.querySelector(".save-group").onclick = function(){
            var records = [];
            det.querySelectorAll(".stu-row").forEach(function(row){
              var v = row.querySelector("select").value;
              if (v) records.push({ student_id: +row.dataset.sid, status: v });
            });
            if (!records.length) { ctx.toast("Kamida bitta status tanlang"); return; }
            var reason = det.querySelector(".reason").value.trim();
            ctx.api("/api/attendance/mark", {
              method: "PUT",
              body: { group_id: gid, day: day, records: records, reason: reason },
            }).then(function(){ ctx.toast("Saqlandi"); reload(); })
              .catch(function(e){ ctx.toast(e.message); });
          };
        });
      }).catch(function(e){ wrap.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
    }
    reload();
  }

  // ---------------- Matrix tab ----------------
  function renderMatrix(container, ctx, state){
    var wrap = document.createElement("div");
    wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
    container.appendChild(wrap);
    var m = state.month || ctx.month();

    function draw(){
      wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
      ctx.api("/api/groups").then(function(groups){
        // groups via manager teachers? Use /api/attendance/day to list groups
        ctx.api("/api/attendance/day").then(function(day){
          var groupList = day.groups.map(function(g){ return { id: g.group_id, name: g.group }; });
          var opts = groupList.map(function(g){ return '<option value="' + g.id + '">' + ctx.esc(g.name) + '</option>'; }).join("");
          wrap.innerHTML = '<div class="card"><div class="row" style="margin-bottom:0">' +
            '<label>Guruh<select id="m-group">' + opts + '</select></label>' +
            '<label>Oy<input type="month" id="m-month" value="' + m + '"></label>' +
            '<label style="flex:0;min-width:0"><span></span><button class="btn g" id="m-load">Koʻrsatish</button></label>' +
            '<label style="flex:0;min-width:0"><span></span><a class="btn g" id="m-csv" href="#" download>CSV</a></label>' +
            '<label style="flex:0;min-width:0"><span></span><button class="btn g" id="m-print">Chop etish</button></label>' +
          '</div></div><div id="m-out"></div>';

          var loadBtn = document.getElementById("m-load");
          var csvBtn = document.getElementById("m-csv");
          var printBtn = document.getElementById("m-print");
          var out = document.getElementById("m-out");

          function loadMatrix(){
            var gid = document.getElementById("m-group").value;
            var mm = document.getElementById("m-month").value;
            if (!gid) { out.innerHTML = '<div class="card">Guruh tanlang</div>'; return; }
            ctx.api("/api/attendance/matrix?group_id=" + gid + "&month=" + mm).then(function(d){
              var head = '<tr><th class="st">Oʻquvchi</th>' + d.days.map(function(x){ return '<th>' + x.slice(5) + '</th>'; }).join("") + '<th>%</th></tr>';
              var rows = d.students.map(function(s){
                var cells = d.days.map(function(x){
                  var v = s.marks[x] || "";
                  var cl = v === "present" ? "p" : v === "absent" ? "a" : v === "excused" ? "e" : "";
                  var ch = v === "present" ? "K" : v === "absent" ? "Y" : v === "excused" ? "S" : "";
                  return '<td class="' + cl + '">' + ch + '</td>';
                }).join("");
                return '<tr><td class="st">' + ctx.esc(s.full_name) + '</td>' + cells + '<td class="pct-cell">' + s.percent + '%</td></tr>';
              }).join("");
              out.innerHTML = '<div class="card"><h3>' + ctx.esc(d.group.name) + ' — ' + ctx.esc(d.month) + '</h3><div style="overflow-x:auto"><table class="matrix"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div></div>';
            }).catch(function(e){ out.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
          }

          loadBtn.onclick = loadMatrix;
          csvBtn.onclick = function(e){
            e.preventDefault();
            var gid = document.getElementById("m-group").value;
            var mm = document.getElementById("m-month").value;
            if (!gid) { ctx.toast("Guruh tanlang"); return; }
            var url = "/api/attendance/matrix?format=csv&group_id=" + gid + "&month=" + mm;
            fetch(url, { headers: { Authorization: "Bearer " + (localStorage.getItem("pt") || "") } })
              .then(function(r){ if (!r.ok) throw new Error("CSV xatosi"); return r.blob(); })
              .then(function(blob){
                var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "davomat-" + mm + ".csv"; a.click();
                setTimeout(function(){ URL.revokeObjectURL(a.href); }, 2000);
              }).catch(function(err){ ctx.toast(err.message); });
          };
          printBtn.onclick = function(){ window.print(); };

          loadMatrix();
        });
      }).catch(function(e){ wrap.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
    }
    draw();
  }

  // ---------------- Absent tab ----------------
  function renderAbsent(container, ctx, state){
    var wrap = document.createElement("div");
    container.appendChild(wrap);
    var day = state.absentDay || today();

    function reload(){
      wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
      Promise.all([
        ctx.api("/api/attendance/absent?day=" + day),
        ctx.api("/api/attendance/streaks"),
      ]).then(function(r){
        var ab = r[0], sk = r[1];
        var abRows = ab.absent.map(function(a){
          var fu = a.followup ? '<span class="chip c-mute">' + ctx.esc(a.followup.status) + '</span>' : "";
          return '<div class="card">' +
            '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">' +
              '<div><b>' + ctx.esc(a.full_name) + '</b> <span class="sub">· ' + ctx.esc(a.group) + '</span></div>' +
              '<div>' + fu + '</div>' +
            '</div>' +
            '<div class="sub" style="margin:6px 0">Telefon: ' + (a.phone ? '<a href="tel:' + ctx.esc(a.phone) + '">' + ctx.esc(a.phone) + '</a>' : "—") +
              ' · Ota-ona: ' + (a.parent_phone ? '<a href="tel:' + ctx.esc(a.parent_phone) + '">' + ctx.esc(a.parent_phone) + '</a>' : "—") + '</div>' +
            '<div class="row" style="margin-bottom:0">' +
              '<label>Holat<select class="fu-status"><option value="called">Qoʻngʻiroq qilindi</option><option value="no_answer">Javob bermadi</option><option value="parent_excused">Sababli (ota-ona)</option><option value="note">Izoh</option></select></label>' +
              '<label>Izoh<input class="fu-note" maxlength="300"></label>' +
              '<label style="flex:0;min-width:0"><span></span><button class="btn g fu-save" data-sid="' + a.student_id + '">Saqlash</button></label>' +
            '</div>' +
          '</div>';
        }).join("") || '<div class="card sub">Bugun yoʻqlar yoʻq</div>';

        var skRows = sk.streaks.map(function(s){
          return '<div class="card"><b>' + ctx.esc(s.full_name) + '</b> <span class="sub">· ' + ctx.esc(s.group) + '</span> — ' + s.days.length + ' kun ketma-ket kelmadi' +
            '<div class="sub">' + s.days.slice(0, 5).join(", ") + (s.days.length > 5 ? "…" : "") + '</div></div>';
        }).join("") || '<div class="card sub">Ketma-ket kelmaganlar yoʻq</div>';

        wrap.innerHTML = '<div class="card"><label>Sana<input type="date" id="abs-day" value="' + day + '"></label></div>' +
          '<h3>Bugun yoʻqlar (' + ab.absent.length + ')</h3>' + abRows +
          '<h3>Ketma-ket kelmaganlar (≥ ' + sk.min + ' kun)</h3>' + skRows;

        document.getElementById("abs-day").onchange = function(e){ day = e.target.value; state.absentDay = day; reload(); };
        document.querySelectorAll(".fu-save").forEach(function(b){
          b.onclick = function(){
            var card = b.closest(".card");
            var status = card.querySelector(".fu-status").value;
            var note = card.querySelector(".fu-note").value.trim();
            ctx.api("/api/attendance/followups", { method: "POST", body: { student_id: +b.dataset.sid, day: day, status: status, note: note } })
              .then(function(res){
                if (res.suggest_excused) {
                  if (confirm("Ota-ona sababli dedi. Belgini «Sababli»ga oʻzgartirilsinmi?")) {
                    ctx.api("/api/attendance/mark", { method: "PUT", body: { group_id: 0, day: day, records: [], reason: "" } })
                      .catch(function(){ /* ignore, user will handle from daily */ });
                    ctx.toast("Kunlik boʻlimidan «Sababli»ga oʻzgartiring");
                  }
                }
                ctx.toast("Saqlandi"); reload();
              }).catch(function(e){ ctx.toast(e.message); });
          };
        });
      }).catch(function(e){ wrap.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
    }
    reload();
  }

  // ---------------- Calendar tab ----------------
  function renderCalendar(container, ctx){
    var wrap = document.createElement("div");
    container.appendChild(wrap);

    function reload(){
      wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
      Promise.all([
        ctx.api("/api/attendance/exceptions"),
        ctx.api("/api/attendance/substitutions"),
      ]).then(function(r){
        var ex = r[0], sb = r[1];
        var exRows = ex.map(function(e){
          return '<tr><td>' + ctx.esc(e.day) + '</td><td>' + (e.group_id || "Barchasi") + '</td><td>' + ctx.esc(e.kind) + '</td><td>' + ctx.esc(e.note || "") + '</td>' +
            '<td><button class="btn g del-ex" data-id="' + e.id + '">Oʻchirish</button></td></tr>';
        }).join("");
        var sbRows = sb.map(function(s){
          return '<tr><td>' + s.group_id + '</td><td>' + s.teacher_id + '</td><td>' + ctx.esc(s.from_day) + ' — ' + ctx.esc(s.to_day) + '</td><td>' + ctx.esc(s.reason || "") + '</td>' +
            '<td><button class="btn g del-sb" data-id="' + s.id + '">Oʻchirish</button></td></tr>';
        }).join("");

        wrap.innerHTML = '' +
          '<div class="card">' +
            '<h3>Dam olish / bekor / qoʻshimcha dars</h3>' +
            '<div class="row">' +
              '<label>Tur<select id="ex-kind"><option value="holiday">Dam olish</option><option value="cancelled">Bekor qilingan</option><option value="extra">Qoʻshimcha dars</option></select></label>' +
              '<label>Boshlanish<input type="date" id="ex-from"></label>' +
              '<label>Tugash (ixtiyoriy)<input type="date" id="ex-to"></label>' +
              '<label>Guruh ID (boʻsh = barchasi)<input type="number" id="ex-gid"></label>' +
              '<label>Izoh<input id="ex-note" maxlength="200"></label>' +
              '<label style="flex:0;min-width:0"><span></span><button class="btn" id="ex-add">Qoʻshish</button></label>' +
            '</div>' +
            '<table><thead><tr><th>Kun</th><th>Guruh</th><th>Tur</th><th>Izoh</th><th></th></tr></thead><tbody>' + (exRows || '<tr><td colspan="5" class="sub">Yoʻq</td></tr>') + '</tbody></table>' +
          '</div>' +
          '<div class="card">' +
            '<h3>Oʻrinbosarlik</h3>' +
            '<div class="row">' +
              '<label>Guruh ID<input type="number" id="sb-gid"></label>' +
              '<label>Oʻqituvchi ID<input type="number" id="sb-tid"></label>' +
              '<label>Boshlanish<input type="date" id="sb-from"></label>' +
              '<label>Tugash<input type="date" id="sb-to"></label>' +
              '<label>Sabab<input id="sb-reason" maxlength="200"></label>' +
              '<label style="flex:0;min-width:0"><span></span><button class="btn" id="sb-add">Qoʻshish</button></label>' +
            '</div>' +
            '<table><thead><tr><th>Guruh</th><th>Oʻqituvchi</th><th>Oraliq</th><th>Sabab</th><th></th></tr></thead><tbody>' + (sbRows || '<tr><td colspan="5" class="sub">Yoʻq</td></tr>') + '</tbody></table>' +
          '</div>';

        document.getElementById("ex-add").onclick = function(){
          var body = { kind: document.getElementById("ex-kind").value, note: document.getElementById("ex-note").value.trim() };
          var from = document.getElementById("ex-from").value;
          var to = document.getElementById("ex-to").value;
          var gid = document.getElementById("ex-gid").value;
          if (from) body.from_day = from;
          if (to) body.to_day = to;
          if (!from && !to) { ctx.toast("Sanani kiriting"); return; }
          if (!body.from_day) body.from_day = from;
          if (!body.to_day) body.to_day = body.from_day;
          if (body.from_day === body.to_day) { body.day = body.from_day; delete body.from_day; delete body.to_day; }
          if (gid) body.group_id = +gid;
          ctx.api("/api/attendance/exceptions", { method: "POST", body: body })
            .then(function(d){ ctx.toast("Qoʻshildi: " + d.created); reload(); })
            .catch(function(e){ ctx.toast(e.message); });
        };
        document.querySelectorAll(".del-ex").forEach(function(b){
          b.onclick = function(){
            if (!confirm("Oʻchirilsinmi?")) return;
            ctx.api("/api/attendance/exceptions/" + b.dataset.id, { method: "DELETE" })
              .then(function(){ reload(); }).catch(function(e){ ctx.toast(e.message); });
          };
        });
        document.getElementById("sb-add").onclick = function(){
          var body = {
            group_id: +document.getElementById("sb-gid").value,
            teacher_id: +document.getElementById("sb-tid").value,
            from_day: document.getElementById("sb-from").value,
            to_day: document.getElementById("sb-to").value,
            reason: document.getElementById("sb-reason").value.trim(),
          };
          if (!body.group_id || !body.teacher_id || !body.from_day || !body.to_day) { ctx.toast("Barcha maydonlarni toʻldiring"); return; }
          ctx.api("/api/attendance/substitutions", { method: "POST", body: body })
            .then(function(){ ctx.toast("Qoʻshildi"); reload(); }).catch(function(e){ ctx.toast(e.message); });
        };
        document.querySelectorAll(".del-sb").forEach(function(b){
          b.onclick = function(){
            if (!confirm("Oʻchirilsinmi?")) return;
            ctx.api("/api/attendance/substitutions/" + b.dataset.id, { method: "DELETE" })
              .then(function(){ reload(); }).catch(function(e){ ctx.toast(e.message); });
          };
        });
      }).catch(function(e){ wrap.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
    }
    reload();
  }

  // ---------------- Suspicious tab ----------------
  function renderSuspicious(container, ctx){
    var wrap = document.createElement("div");
    wrap.innerHTML = '<div class="card">Yuklanmoqda…</div>';
    container.appendChild(wrap);
    ctx.api("/api/attendance/suspicious").then(function(d){
      var flagHtml = d.flagged.map(function(f){
        return '<div class="card"><b>' + ctx.esc(f.group) + '</b> · ' + ctx.esc(f.teacher) + ' — ' + f.percent + '% (' + f.all_present + '/' + f.batches + ')</div>';
      }).join("") || '<div class="card sub">Shubhali natijalar yoʻq</div>';
      var rowHtml = d.rows.map(function(x){
        return '<tr><td>' + ctx.esc(x.group) + '</td><td>' + ctx.esc(x.teacher) + '</td><td>' + x.batches + '</td><td>' + x.all_present + '</td><td class="pct-cell">' + x.percent + '%</td></tr>';
      }).join("") || '<tr><td colspan="5" class="sub">Yoʻq</td></tr>';
      wrap.innerHTML = '<div class="card"><h3>Shubhali guruhlar (≥ 90% va ≥ 8 ta toʻliq)</h3>' + flagHtml + '</div>' +
        '<div class="card"><h3>Barcha statistika</h3><table><thead><tr><th>Guruh</th><th>Oʻqituvchi</th><th>Toʻplam</th><th>100%</th><th>%</th></tr></thead><tbody>' + rowHtml + '</tbody></table></div>';
    }).catch(function(e){ wrap.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
  }

  // ---------------- Page entry ----------------
  window.Panel.register({
    id: "attendance", title: "Davomat", icon: "✓",
    render: function(main, ctx){
      var state = { tab: "daily" };
      function draw(){
        main.innerHTML = "";
        subTabs(ctx, main, state.tab, function(t){ state.tab = t; draw(); });
        var box = document.createElement("div");
        main.appendChild(box);
        if (state.tab === "daily") renderDaily(box, ctx, state);
        else if (state.tab === "matrix") renderMatrix(box, ctx, state);
        else if (state.tab === "absent") renderAbsent(box, ctx, state);
        else if (state.tab === "calendar") renderCalendar(box, ctx);
        else if (state.tab === "suspicious") renderSuspicious(box, ctx);
      }
      draw();
    }
  });
})();
