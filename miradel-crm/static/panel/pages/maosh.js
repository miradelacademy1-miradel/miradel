(function(){
  window.Panel.register({
    id: "maosh", title: "Maosh", icon: "💵",
    render: function(main, ctx){
      var state = { month: ctx.month() };
      main.innerHTML = '<div class="card"><div class="row"><label>Oy<input type="month" id="s-month" value="'+state.month+'"></label></div></div><div id="s-out"></div>';
      
      function reload(){
        ctx.api("/manager/salary?month="+state.month).then(function(d){
          var html = '<div class="card"><h3>Hisoblangan: '+ctx.fmtMoney(d.totals.amount_total)+'</h3><table><tr><th>Oʻqituvchi</th><th>Hisoblangan</th><th>Toʻlangan</th><th>Qoldiq</th><th></th></tr>' +
            d.rows.map(function(r){ return '<tr><td>'+ctx.esc(r.full_name)+'</td><td>'+ctx.fmtMoney(r.amount_total)+'</td><td>'+ctx.fmtMoney(r.paid)+'</td><td>'+ctx.fmtMoney(r.balance_total)+'</td><td><button class="btn g s-row" data-id="'+r.id+'">Batafsil</button></td></tr>'; }).join('') + '</table></div>';
          document.getElementById("s-out").innerHTML = html;
          
          document.querySelectorAll(".s-row").forEach(function(b){
            b.onclick = function(){ openDrawer(parseInt(b.dataset.id)); };
          });
        }).catch(function(e){ document.getElementById("s-out").innerHTML = '<div class="card" style="color:var(--bad)">'+ctx.esc(e.message)+'</div>'; });
      }
      
      function openDrawer(id){
        ctx.api("/manager/salary/sheet?teacher_id="+id+"&month="+state.month).then(function(d){
          var html = '<div style="display:flex;justify-content:space-between"><h2>'+ctx.esc(d.teacher)+'</h2><button class="btn g" id="d-close">Yopish</button></div>' +
            '<p>Rejim: '+d.mode+' · Stavka: '+d.rate+' · Darslar: '+d.lessons_list.length+'</p>' +
            '<h3>Mukofot / Jarima</h3>' +
            '<div class="row"><label>Summa (manfiy = jarima)<input type="number" id="a-amt"></label><label>Sabab<input id="a-reason"></label><button class="btn" id="a-add">Qoʻshish</button></div>' +
            '<div>' + d.adjustments.map(function(a){ return '<div>'+a.date.slice(0,10)+' · '+ctx.fmtMoney(a.amount)+' · '+ctx.esc(a.reason)+' <button class="btn g" onclick="voidAdj('+a.id+')">Oʻchirish</button></div>'; }).join('') + '</div>' +
            '<h3>Toʻlovlar</h3><div>' + d.payouts.map(function(p){ return '<div>'+p.date+' · '+ctx.fmtMoney(p.amount)+' · '+ctx.esc(p.note)+'</div>'; }).join('') + '</div>' +
            '<button class="btn g" style="margin-top:16px" onclick="window.print()">Chop etish</button>';
            
          document.getElementById("s-out").innerHTML = '<div class="card">'+html+'</div>';
          document.getElementById("d-close").onclick = reload;
          
          document.getElementById("a-add").onclick = function(){
            var amt = +document.getElementById("a-amt").value;
            var reason = document.getElementById("a-reason").value;
            if(!amt || reason.length < 3) { ctx.toast("Summa va sabab kiriting"); return; }
            ctx.api("/manager/salary/adjustments", {method:"POST", body:{teacher_id: id, month: state.month, amount: amt, reason: reason}}).then(function(){ openDrawer(id); }).catch(function(e){ ctx.toast(e.message); });
          };
          
          window.voidAdj = function(aid){
            ctx.api("/manager/salary/adjustments/"+aid+"/void", {method:"POST"}).then(function(){ openDrawer(id); }).catch(function(e){ ctx.toast(e.message); });
          };
        });
      }
      
      document.getElementById("s-month").onchange = function(e){ state.month = e.target.value; reload(); };
      reload();
    }
  });
})();
