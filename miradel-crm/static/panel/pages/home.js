(function(){
  window.Panel.register({
    id: "home", title: "Bosh sahifa", icon: "🏠",
    render: function(main, ctx){
      main.innerHTML = '<div class="card">Yuklanmoqda…</div>';
      ctx.api("/api/attendance/summary").then(function(d){
        var missingRows = d.missing.map(function(m){
          return '<tr><td><b>' + ctx.esc(m.group) + '</b></td><td>' + ctx.esc(m.teacher || "—") + '</td>' +
            '<td><a class="chip c-warn" href="#attendance">Belgilash →</a></td></tr>';
        }).join("") || '<tr><td colspan="3" class="sub">Bugun barcha darslar belgilangan ✅</td></tr>';
        main.innerHTML = '' +
          '<h2>Bugun — ' + ctx.esc(d.today) + '</h2>' +
          '<div class="row" style="margin-bottom:16px">' +
            '<div class="card" style="flex:1;min-width:140px"><h3 style="margin:0;font-size:.7rem;color:var(--mute)">DARS BOR</h3><div style="font-size:1.8rem;font-weight:800">' + d.groups_with_lesson + '</div></div>' +
            '<div class="card" style="flex:1;min-width:140px"><h3 style="margin:0;font-size:.7rem;color:var(--mute)">BELGILANGAN</h3><div style="font-size:1.8rem;font-weight:800;color:var(--ok)">' + d.marked + '</div></div>' +
            '<div class="card" style="flex:1;min-width:140px"><h3 style="margin:0;font-size:.7rem;color:var(--mute)">BELGILANMAGAN</h3><div style="font-size:1.8rem;font-weight:800;color:var(--bad)">' + d.missing.length + '</div></div>' +
            '<div class="card" style="flex:1;min-width:140px"><h3 style="margin:0;font-size:.7rem;color:var(--mute)">KELDI / KELMADI</h3><div style="font-size:1.4rem;font-weight:800">' + d.present_total + ' / <span style="color:var(--bad)">' + d.absent_total + '</span></div></div>' +
          '</div>' +
          '<div class="card"><h3>Bugun belgilanmagan guruhlar</h3><table><thead><tr><th>Guruh</th><th>Oʻqituvchi</th><th></th></tr></thead><tbody>' + missingRows + '</tbody></table></div>';
      }).catch(function(e){ main.innerHTML = '<div class="card" style="color:var(--bad)">' + ctx.esc(e.message) + '</div>'; });
    }
  });
})();
