/* Tuiú — shell de navegação compartilhado.
   Um só componente, injetado em toda página autenticada, consciente de papel.
   Barra fixa no topo (padrão do veredas) + busca global do operador.
   Tema clássico preservado; quando <html data-tema="cartorio"> está ativo,
   a barra assume o visual Cartório (papel, filetes, rubricas).
   Inclua com:  <script src="/nav.js" defer></script>  */
(function () {
  var PAL = { bg: "#0e1620", barra: "#0b1017", linha: "#1e2a3a", tx: "#dbe6f4",
              dim: "#8ba3bf", acento: "#4da3ff" };
  var PAL_CART = { bg: "#faf7ee", barra: "#f5f1e6", linha: "#ddd3bc", linha2: "#c9bda0",
                   tx: "#221c12", dim: "#5c5344", acento: "#b23a2a", selo: "#b23a2a" };
  var AQUI = (location.pathname.replace(/\/index\.html$/, "/")) || "/";

  function ativo(u) { var a = u.split("?")[0]; return a === "/" ? AQUI === "/" : AQUI === a; }
  function cartorio() { return document.documentElement.getAttribute("data-tema") === "cartorio"; }

  var CSS = ""
    + "body{padding-top:64px!important}"
    + "#tuiunav{position:fixed;top:0;left:0;right:0;height:50px;z-index:900;background:" + PAL.barra
      + ";border-bottom:1px solid " + PAL.linha + ";display:flex;align-items:center;gap:5px;padding:0 16px;"
      + "font:13px/1.4 system-ui,Segoe UI,sans-serif}"
    + "#tuiunav .marca{font-weight:700;font-size:15px;color:" + PAL.tx + ";letter-spacing:.3px;margin-right:10px;text-decoration:none}"
    + "#tuiunav .marca span{color:" + PAL.acento + "}"
    + "#tuiunav a.tab{color:" + PAL.dim + ";text-decoration:none;padding:6px 10px;border-radius:8px;white-space:nowrap}"
    + "#tuiunav a.tab:hover{color:" + PAL.tx + ";background:#141d29}"
    + "#tuiunav a.tab.on{color:" + PAL.tx + ";background:#16212f;box-shadow:inset 0 -2px 0 " + PAL.acento + "}"
    + "#tuiunav .sp{flex:1}"
    + "#tuiunav .busca{position:relative}"
    + "#tuiunav .busca input{background:#0d141d;border:1px solid " + PAL.linha + ";color:" + PAL.tx
      + ";border-radius:8px;padding:6px 10px;width:230px;font-size:13px;transition:width .12s}"
    + "#tuiunav .busca input:focus{border-color:" + PAL.acento + ";outline:none;width:300px}"
    + "#tuiunav .res{position:absolute;top:40px;right:0;width:370px;background:" + PAL.bg
      + ";border:1px solid " + PAL.linha + ";border-radius:10px;overflow:hidden;box-shadow:0 12px 30px #0009;display:none}"
    + "#tuiunav .res.aberto{display:block}"
    + "#tuiunav .res a{display:block;padding:8px 12px;text-decoration:none;color:" + PAL.tx + ";border-bottom:1px solid " + PAL.linha + "}"
    + "#tuiunav .res a:last-child{border-bottom:0}"
    + "#tuiunav .res a:hover{background:#141d29}"
    + "#tuiunav .res a small{display:block;color:" + PAL.dim + ";font-size:11.5px;margin-top:1px}"
    + "#tuiunav .res .tag{font-size:10px;color:" + PAL.acento + ";text-transform:uppercase;letter-spacing:.5px;margin-right:6px}"
    + "#tuiunav .menu{position:relative}"
    + "#tuiunav .menu>button{background:none;border:1px solid " + PAL.linha + ";color:" + PAL.dim
      + ";border-radius:8px;padding:6px 10px;cursor:pointer;font-size:12.5px}"
    + "#tuiunav .menu>button:hover{color:" + PAL.tx + ";border-color:" + PAL.acento + "}"
    + "#tuiunav .drop{position:absolute;top:40px;right:0;background:" + PAL.bg + ";border:1px solid " + PAL.linha
      + ";border-radius:10px;overflow:hidden;display:none;min-width:170px;box-shadow:0 12px 30px #0009}"
    + "#tuiunav .drop.aberto{display:block}"
    + "#tuiunav .drop a,#tuiunav .drop button.op{display:block;width:100%;text-align:left;padding:8px 13px;color:" + PAL.tx
      + ";text-decoration:none;font-size:13px;background:none;border:0;cursor:pointer;font-family:inherit}"
    + "#tuiunav .drop a:hover,#tuiunav .drop button.op:hover{background:#141d29}"
    + "#tuiunav .drop .rotulo{padding:7px 13px 3px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:" + PAL.dim + "}"
    + "#tuiunav .drop button.op .marca-tema{float:right;color:" + PAL.acento + "}"
    + "@media(max-width:860px){#tuiunav .tab.sec{display:none}#tuiunav .busca input{width:120px}#tuiunav .busca input:focus{width:170px}}"
    /* ===== Cartório ===== */
    + "html[data-tema=cartorio] body{padding-top:70px!important}"
    + "html[data-tema=cartorio] #tuiunav{height:58px;background:" + PAL_CART.barra
      + ";border-bottom:2px solid " + PAL_CART.tx
      + ";font-family:Archivo,system-ui,sans-serif}"
    + "html[data-tema=cartorio] #tuiunav .marca{font:italic 600 23px/1 Fraunces,Georgia,serif;color:" + PAL_CART.tx
      + ";letter-spacing:.01em;margin-right:16px}"
    + "html[data-tema=cartorio] #tuiunav .marca span{font-style:normal;color:" + PAL_CART.selo + "}"
    + "html[data-tema=cartorio] #tuiunav a.tab{font:600 10.5px 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.15em;"
      + "text-transform:uppercase;color:" + PAL_CART.dim + ";border:1px solid transparent;border-radius:0;padding:7px 12px}"
    + "html[data-tema=cartorio] #tuiunav a.tab:hover{color:" + PAL_CART.tx + ";background:none;border-color:" + PAL_CART.linha2 + "}"
    + "html[data-tema=cartorio] #tuiunav a.tab.on{color:" + PAL_CART.selo + ";background:rgba(178,58,42,.05);"
      + "border-color:" + PAL_CART.selo + ";box-shadow:none}"
    + "html[data-tema=cartorio] #tuiunav .busca input{background:" + PAL_CART.bg + ";border:1px solid " + PAL_CART.linha2
      + ";border-radius:0;color:" + PAL_CART.tx + ";font-size:12.5px}"
    + "html[data-tema=cartorio] #tuiunav .busca input:focus{border-color:" + PAL_CART.tx
      + ";box-shadow:3px 3px 0 rgba(34,28,18,.12)}"
    + "html[data-tema=cartorio] #tuiunav .res{background:" + PAL_CART.bg + ";border:1px solid " + PAL_CART.linha2
      + ";border-radius:0;box-shadow:5px 5px 0 rgba(34,28,18,.12)}"
    + "html[data-tema=cartorio] #tuiunav .res a{color:" + PAL_CART.tx + ";border-bottom:1px solid " + PAL_CART.linha + "}"
    + "html[data-tema=cartorio] #tuiunav .res a:hover{background:rgba(34,28,18,.04)}"
    + "html[data-tema=cartorio] #tuiunav .res a small{color:" + PAL_CART.dim + "}"
    + "html[data-tema=cartorio] #tuiunav .res .tag{color:" + PAL_CART.selo + "}"
    + "html[data-tema=cartorio] #tuiunav .menu>button{border:1px solid " + PAL_CART.linha2 + ";border-radius:0;"
      + "color:" + PAL_CART.dim + ";font:600 10.5px 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}"
    + "html[data-tema=cartorio] #tuiunav .menu>button:hover{color:" + PAL_CART.tx + ";border-color:" + PAL_CART.tx + "}"
    + "html[data-tema=cartorio] #tuiunav .drop{background:" + PAL_CART.bg + ";border:1px solid " + PAL_CART.linha2
      + ";border-radius:0;box-shadow:5px 5px 0 rgba(34,28,18,.12)}"
    + "html[data-tema=cartorio] #tuiunav .drop a,html[data-tema=cartorio] #tuiunav .drop button.op{color:" + PAL_CART.tx + "}"
    + "html[data-tema=cartorio] #tuiunav .drop a:hover,html[data-tema=cartorio] #tuiunav .drop button.op:hover{background:rgba(34,28,18,.05)}"
    + "html[data-tema=cartorio] #tuiunav .drop .rotulo{color:" + PAL_CART.dim + "}"
    + "html[data-tema=cartorio] #tuiunav .drop button.op .marca-tema{color:" + PAL_CART.selo + "}"
    /* ===== Leitor: esconde os controles de escrita (o backend também barra) ===== */
    + "html.leitor .acts,html.leitor .dch,html.leitor .acoes,html.leitor .acao,html.leitor .sw,html.leitor .edita{display:none!important}"
    + "#tuiunav .lemode{font:600 10px 'IBM Plex Mono',ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:"
      + PAL.dim + ";border:1px solid " + PAL.linha + ";border-radius:6px;padding:3px 8px;margin-left:4px;white-space:nowrap}"
    + "html[data-tema=cartorio] #tuiunav .lemode{color:" + PAL_CART.selo + ";border-color:" + PAL_CART.linha2 + ";border-radius:0}";

  var TABS = [["Cockpit", "/"], ["Mesa", "/mesa.html"], ["Fila", "/fila.html"], ["Carteira", "/carteira.html"],
              ["Inteligência", "/inteligencia.html"], ["Guia interativo", "/guia.html"]];
  var MAIS = [["Instruções", "/instrucoes.html"], ["Agenda de prazos", "/agenda.html"],
              ["Andamento", "/eventos.html"], ["Notificações", "/notificacoes.html"],
              ["Normas", "/normas.html"], ["Prestação de contas", "/prestacao.html"],
              ["Uso do guia", "/guia-uso.html"]];

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function montar(user) {
    var st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
    var nav = document.createElement("nav"); nav.id = "tuiunav";
    // operador E leitor têm o nav interno (a carteira toda); o leitor só não
    // ganha os controles de edição/admin (config já é admin-only, user.admin).
    var op = !!(user && (user.papel === "operador" || user.papel === "leitor"));
    var leitor = !!(user && user.papel === "leitor");
    if (leitor) document.documentElement.classList.add("leitor");   // CSS esconde os controles de escrita
    var lemode = leitor ? '<span class="lemode" title="você consulta a carteira; edições ficam ocultas">modo leitura</span>' : "";
    var tabs = "", busca = "", mais = "";
    if (op) {
      tabs = TABS.map(function (x) { return '<a class="tab ' + (ativo(x[1]) ? "on" : "") + '" href="' + x[1] + '">' + x[0] + "</a>"; }).join("");
      var itensMais = user.admin ? MAIS.concat([["⚙ Configurações", "/config.html"]]) : MAIS;
      mais = '<div class="menu" id="tmais"><button>Mais &#9662;</button><div class="drop">'
        + itensMais.map(function (x) { return '<a href="' + x[1] + '">' + x[0] + "</a>"; }).join("") + "</div></div>";
      busca = '<div class="busca"><input id="tnq" placeholder="Buscar cliente, proposta, órgão…" autocomplete="off" spellcheck="false"><div class="res" id="tnr"></div></div>';
    } else if (user) {
      var doc = user.doc_cliente || "";
      tabs = '<a class="tab ' + (AQUI.indexOf("/cliente") === 0 ? "on" : "") + '" href="/cliente.html?doc=' + doc + '">Minha ficha</a>'
        + '<a class="tab ' + (ativo("/prestacao.html") ? "on" : "") + '" href="/prestacao.html">Prestação</a>'
        + '<a class="tab ' + (ativo("/guia.html") ? "on" : "") + '" href="/guia.html">Guia interativo</a>'
        + '<a class="tab ' + (ativo("/instrucoes.html") ? "on" : "") + '" href="/instrucoes.html">Instruções</a>';
    }
    var quem = esc((user && (user.nome || user.login)) || "conta");
    var temaAtual = (window.TuiuTema && TuiuTema.atual()) || "cartorio";
    var seletor = '<div class="rotulo">Tema</div>'
      + '<button class="op" data-tema="claro">Escuro (clássico)<span class="marca-tema">' + (temaAtual !== "cartorio" ? "✓" : "") + '</span></button>'
      + '<button class="op" data-tema="cartorio">Cartório (papel)<span class="marca-tema">' + (temaAtual === "cartorio" ? "✓" : "") + '</span></button>';
    nav.innerHTML = '<a class="marca" href="/">Tui<span>ú</span></a>' + tabs + mais + lemode
      + '<span class="sp"></span>' + busca
      + '<div class="menu" id="tuser"><button>' + quem + ' &#9662;</button>'
      + '<div class="drop"><a href="/conta.html">Conta</a>' + seletor + '<a href="#" id="tsair">Sair</a></div></div>';
    document.body.insertBefore(nav, document.body.firstChild);
    wire(op);
  }

  function wire(op) {
    var botoes = document.querySelectorAll("#tuiunav .menu>button");
    for (var i = 0; i < botoes.length; i++) {
      botoes[i].onclick = function (e) {
        e.stopPropagation();
        var d = this.nextElementSibling, abertos = document.querySelectorAll("#tuiunav .drop");
        for (var j = 0; j < abertos.length; j++) if (abertos[j] !== d) abertos[j].classList.remove("aberto");
        d.classList.toggle("aberto");
      };
    }
    document.addEventListener("click", function () {
      var x = document.querySelectorAll("#tuiunav .drop,#tuiunav .res");
      for (var k = 0; k < x.length; k++) x[k].classList.remove("aberto");
    });
    var sair = document.getElementById("tsair");
    if (sair) sair.onclick = function (e) { e.preventDefault();
      fetch("/api/logout", { method: "POST" }).then(function () { location.href = "/login.html"; }); };
    var ops = document.querySelectorAll("#tuiunav .drop button.op[data-tema]");
    for (var b = 0; b < ops.length; b++) {
      ops[b].onclick = function (e) {
        e.stopPropagation();
        if (window.TuiuTema) { TuiuTema.definir(this.getAttribute("data-tema")); location.reload(); }
      };
    }
    if (!op) return;
    var q = document.getElementById("tnq"), r = document.getElementById("tnr"), tmr = null;
    q.onclick = function (e) { e.stopPropagation(); if (r.innerHTML) r.classList.add("aberto"); };
    q.oninput = function () {
      clearTimeout(tmr); var v = q.value.trim();
      if (v.length < 2) { r.classList.remove("aberto"); return; }
      tmr = setTimeout(function () {
        fetch("/api/busca?q=" + encodeURIComponent(v)).then(function (x) { return x.json(); }).then(function (d) {
          var rs = d.resultados || [];
          r.innerHTML = rs.length
            ? rs.map(function (o) { return '<a href="' + o.url + '"><span class="tag">' + esc(o.tipo) + "</span>"
                + esc(o.titulo) + "<small>" + esc(o.sub || "") + "</small></a>"; }).join("")
            : '<a href="#" onclick="return false"><small>nada encontrado para "' + esc(v) + '"</small></a>';
          r.classList.add("aberto");
        });
      }, 180);
    };
    q.onkeydown = function (e) {
      if (e.key === "Enter") { var a = r.querySelector('a[href]:not([href="#"])'); if (a) location.href = a.getAttribute("href"); }
      if (e.key === "Escape") r.classList.remove("aberto");
    };
  }

  fetch("/api/sessao").then(function (r) { return r.json(); })
    .then(function (s) { montar(s && s.usuario); })
    .catch(function () { montar(null); });
})();
