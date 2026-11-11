(function(){
  window.Panel.register({
    id: "moliya", title: "Moliya", icon: "💰",
    render: function(main, ctx){
      var state = { month: ctx.month(), q: "", filter: "all" };
      main.innerHTML = '<div class="card"><div class="row"><label>Oy<input type="month" id="m-month" value="'+state.month+'"></label><label>Qidirish<input id="m-q" placeholder="Ism yoki guruh"></label><label>Holat<select id="m-filter"><option value="all">Hammasi</option><option value="debt">Qarzdor</option><option value="paid">Toʻlagan</option></select></label><button class="btn" id="m-gen">Invoyslarni yaratish</button></div></div><div id="m-out"></div>';
      
      function reload(){
        ctx.api("/manager/finance?month="+state.month).then(function(d){
          var rows = d.rows.filter(function(r){
            if(state.filter === "debt" && !(r.fee > 0 && r.left > 0)) return false;
            if(state.filter === "paid" && r.status !== "paid") return false;
            var term = state.q.toLowerCase();
            return !term || (r.full_name + " " + r.group).toLowerCase().indexOf(term) >= 0;
          });
          
          var html = '<div class="card"><div style="display:flex;gap:16px;margin-bottom:16px"><div><b>Tushum:</b> '+ctx.fmtMoney(d.totals.collected)+'</div><div><b>Kutilgan:</b> '+ctx.fmtMoney(d.totals.expected)+'</div><div><b>Qarzdorlar:</b> '+d.totals.debtors+'</div></div>' +
            '<table><tr><th>Oʻquvchi</th><th>Guruh</th><th>Toʻlangan / Narx</th><th>Holat</th></tr>' +
            rows.map(function(r){ return '<tr class="m-row" style="cursor:pointer" data-id="'+r.id+'"><td>'+ctx.esc(r.full_name)+'</td><td>'+ctx.esc(r.group)+'</td><td>'+ctx.fmtMoney(r.paid)+' / '+(r.fee?ctx.fmtMoney(r.fee):"—")+'</td><td>'+r.status+'</td></tr>'; }).join('') +
            '</table></div>';
          document.getElementById("m-out").innerHTML = html;
          
          document.querySelectorAll(".m-row").forEach(function(tr){
            tr.onclick = function(){ openDrawer(parseInt(tr.dataset.id), d.rows.find(function(x){return x.id === parseInt(tr.dataset.id);})); };
          });
        }).catch(function(e){ document.getElementById("m-out").innerHTML = '<div class="card" style="color:var(--bad)">'+ctx.esc(e.message)+'</div>'; });
      }
      
      function openDrawer(id, row){
        ctx.api("/manager/payments?student_id="+id).then(function(pays){
          var html = '<div style="display:flex;justify-content:space-between"><h2>'+ctx.esc(row.full_name)+'</h2><button class="btn g" id="d-close">Yopish</button></div>' +
            '<p>Guruh: '+ctx.esc(row.group)+' · Narx: '+ctx.fmtMoney(row.fee)+' · Qoldiq: '+ctx.fmtMoney(row.left)+'</p>' +
            '<div class="row"><label>Summa<input type="number" id="d-amount" value="'+(row.left || 0)+'"></label><label>Usul<select id="d-method"><option value="cash">Naqd</option><option value="card">Karta</option><option value="transfer">Oʻtkazma</option></select></label><label>Izoh<input id="d-note"></label></div>' +
            '<label style="display:flex;gap:8px;margin:10px 0"><input type="checkbox" id="d-alloc"> Eng eski qarzdan boshlab taqsimlash</label>' +
            '<button class="btn" id="d-pay">Toʻlov qabul qilish</button>' +
            '<h3>Toʻlovlar tarixi</h3>' +
            (pays.length ? pays.map(function(p){ return '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)"><div>'+p.paid_on+' · '+ctx.fmtMoney(p.amount)+' · '+p.method+' <br><small>'+ctx.esc(p.note)+'</small></div><div><button class="btn g" onclick="window.printReceipt('+p.id+')">Chek</button> '+(p.voided?'<span style="color:red">Bekor</span>':'<button class="btn g" onclick="voidPay('+p.id+')">Bekor</button>')+'</div></div>'; }).join('') : '<p>Toʻlovlar yoʻq</p>');
          
          document.getElementById("m-out").innerHTML = '<div class="card">'+html+'</div>';
          document.getElementById("d-close").onclick = reload;
          
          document.getElementById("d-pay").onclick = function(){
            var amt = +document.getElementById("d-amount").value;
            if(amt <= 0) return;
            ctx.api("/manager/payments", {method:"POST", body:{
              student_id: id, month: state.month, amount: amt, method: document.getElementById("d-method").value,
              note: document.getElementById("d-note").value, allocate_oldest: document.getElementById("d-alloc").checked
            }}).then(function(){
              ctx.toast("Toʻlov qabul qilindi");
              reload();
            }).catch(function(e){ ctx.toast(e.message); });
          };
          
          window.printReceipt = function(pid){
            ctx.api("/manager/payments/"+pid+"/receipt").then(function(r){
              var rHtml = '<div style="background:#fff;color:#000;padding:20px;border:2px solid #000;max-width:400px;margin:0 auto">' +
                '<h2 style="text-align:center;margin:0 0 10px">Miradel Academy</h2>' +
                '<p style="text-align:center;margin:0 0 20px">Chek №: '+r.receipt_no+'</p>' +
                '<p>Oʻquvchi: <b>'+ctx.esc(r.student)+'</b></p>' +
                '<p>Guruh: '+ctx.esc(r.group)+'</p>' +
                '<p>Oy: '+r.month+'</p>' +
                '<p>Summa: <b>'+ctx.fmtMoney(r.amount)+'</b></p>' +
                '<p>Usul: '+r.method+'</p>' +
                '<p>Sana: '+r.paid_on+'</p>' +
                (r.voided ? '<h1 style="color:red;text-align:center;transform:rotate(-15deg)">BEKOR QILINGAN</h1>' : '') +
                '</div>';
              var w = window.open('', '_blank');
              w.document.write('<html><head><title>Chek</title><style>body{font-family:sans-serif;padding:20px}</style></head><body>'+rHtml+'<script>window.print()<\/script></body></html>');
              w.document.close();
            });
          };
          
          window.voidPay = function(pid){
            if(!confirm("Toʻlov bekor qilinsinmi?")) return;
            ctx.api("/manager/payments/"+pid+"/void", {method:"POST"}).then(function(){ reload(); }).catch(function(e){ ctx.toast(e.message); });
          };
        });
      }
      
      document.getElementById("m-month").onchange = function(e){ state.month = e.target.value; reload(); };
      document.getElementById("m-q").oninput = function(e){ state.q = e.target.value; reload(); };
      document.getElementById("m-filter").onchange = function(e){ state.filter = e.target.value; reload(); };
      document.getElementById("m-gen").onclick = function(){
        ctx.api("/manager/invoices/generate", {method:"POST", body:{month: state.month}}).then(function(d){
          ctx.toast(d.created + " ta invoys yaratildi");
          reload();
        }).catch(function(e){ ctx.toast(e.message); });
      };
      reload();
    }
  });
})();
