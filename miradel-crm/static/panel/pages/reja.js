(function(){
  window.Panel.register({
    id: "reja", title: "Reja", icon: "📝",
    render: function(main, ctx){
      main.innerHTML = '<div class="card">Yuklanmoqda...</div>';
      ctx.api("/manager/plans").then(function(plans){
        var html = '<div class="card"><table><tr><th>Oʻqituvchi</th><th>Vazifa</th><th>Muddat</th><th>Holat</th></tr>' +
          plans.map(function(p){ return '<tr><td>'+ctx.esc(p.teacher_name)+'</td><td>'+ctx.esc(p.title)+'</td><td>'+ctx.esc(p.due_date||"—")+'</td><td>'+p.status+'</td></tr>'; }).join('') + '</table></div>';
        main.innerHTML = html;
      }).catch(function(e){ main.innerHTML = '<div class="card" style="color:var(--bad)">'+ctx.esc(e.message)+'</div>'; });
    }
  });
})();
