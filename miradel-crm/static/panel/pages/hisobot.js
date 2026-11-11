(function(){
  window.Panel.register({
    id: "hisobot", title: "Hisobot", icon: "📊",
    render: function(main, ctx){
      main.innerHTML = '<div class="card"><h3>Hisobotlar</h3><p>Bu boʻlim admin paneldagi hisobotlarga havola qiladi. (TZ-3)</p>' +
        '<ul><li><a href="/admin/#rep" target="_blank">Admin panel → Hisobotlar</a></li></ul></div>';
    }
  });
})();
