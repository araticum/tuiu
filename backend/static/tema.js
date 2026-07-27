/* Tuiú · seletor de tema
   Lê o cookie "tuiu_tema" (claro|cartorio) e aplica <html data-tema="...">
   + body.tema-cartorio antes do primeiro paint. Expõe window.TuiuTema
   para o nav desenhar o seletor. O tema clássico é o padrão (sem cookie). */
(function () {
  var TEMAS = { cartorio: "Cartório (papel)", claro: "Escuro (clássico)" };

  function ler() {
    var m = document.cookie.match(/(?:^|;\s*)tuiu_tema=(\w+)/);
    var t = m && m[1];
    if (t) return t;
    try { return localStorage.getItem("tuiu_tema") || "cartorio"; } catch (e) { return "claro"; }
  }

  function aplicar(t) {
    var raiz = document.documentElement;
    if (t === "cartorio") {
      raiz.setAttribute("data-tema", "cartorio");
      if (document.body) document.body.classList.add("tema-cartorio");
      else document.addEventListener("DOMContentLoaded", function () {
        document.body.classList.add("tema-cartorio");
      });
    } else {
      raiz.removeAttribute("data-tema");
      if (document.body) document.body.classList.remove("tema-cartorio");
    }
  }

  function definir(t) {
    document.cookie = "tuiu_tema=" + t + ";path=/;max-age=31536000;SameSite=Lax";
    try { localStorage.setItem("tuiu_tema", t); } catch (e) {}
    aplicar(t);
  }

  var atual = ler();
  aplicar(atual);

  window.TuiuTema = {
    atual: function () { return ler(); },
    definir: definir,
    nomes: TEMAS
  };
})();
