(function(){
  window.Panel.register({
    id: "qarzdorlar", title: "Qarzdorlar", icon: "⚠️",
    render: function(main, ctx){
      var state = { upto: ctx.month(), q: "" };
      main.innerHTML = '<div class="card"><div class="row"><label>Oy (gacha)<input type="month" id="q-upto" value="'+state.upto+'"></label><label>Qidirish<input id="q-q" placeholder="FIO yoki telefon"></label><button class="btn g" id="q-print">Chop etish</button></div></div><div id="q-out"></div>';
      
      function reload(){
        ctx.api("/manager/debts?upto="+state.upto+"&q="+encodeURIComponent(state.q)).then(function(d){
          var html = '<div class="card"><h3>Jami qarz: '+ctx.fmtMoney(d.total_left)+'</h3><table><tr><th>Oʻquvchi</th><th>Guruh</th><th>Telefonlar</th><th>Qarzlar</th><th>Jami</th></tr>' +
            d.rows.map(function(r){
              var mRows = r.months.map(function(m){ return m.month + ': '+ctx.fmtMoney(m.left); }).join('<br>');
              return '<tr><td>'+ctx.esc(r.student)+'</td><td>'+ctx.esc(r.group)+'</td><td>'+ctx.esc(r.phone)+'<br>'+ctx.esc(r.parent_phone)+'</td><td>'+mRows+'</td><td><b>'+ctx.fmtMoney(r.total_left)+'</b></td></tr>';
            }).join('') + '</table></div>';
          document.getElementById("q-out").innerHTML = html;
        }).catch(function(e){ document.getElementById("q-out").innerHTML = '<div class="card" style="color:var(--bad)">'+ctx.esc(e.message)+'</div>'; });
      }
      
      document.getElementById("q-upto").onchange = function(e){ state.upto = e.target.value; reload(); };
      document.getElementById("q-q").oninput = function(e){ state.q = e.target.value; reload(); };
      document.getElementById("q-print").onclick = function(){ window.print(); };
      reload();
    }
  });
})();
