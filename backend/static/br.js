/* Tuiú · português correto no console — o par de `backend/app/texto_br.py`.
 *
 * Regra da casa (dono, 29/07/2026): nada que chegue a uma pessoa sai fora da
 * norma culta. Aqui isso mata o plural entre parênteses — `${n} item(ns)` —, que
 * é fuga: o número está na mão na hora de escrever, então "1 item" ou "9 itens"
 * é decidível, e o parêntese só transfere para quem lê um trabalho que era nosso.
 *
 * Carrega SÍNCRONO no <head>, junto de tema.js e antes de qualquer script inline
 * da página: `nav.js` tem `defer` e só executa depois do parse, então uma função
 * que mora nele não existe para código que roda durante a montagem da tela.
 *
 * `qtd` exige singular E plural de propósito, igual ao lado Python: um
 * pluralizador automático erraria em `item -> itens`, `mês -> meses`,
 * `cidadão -> cidadãos`, e errar calado é pior do que escrever os dois.
 */
(function () {
  "use strict";

  /** qtd(3, "pendência", "pendências") -> "3 pendências". Zero é plural em
   *  português ("0 pendências"), e a concordância vai pelo módulo do número. */
  window.qtd = function (n, singular, plural) {
    var v = Number(n);
    if (!isFinite(v)) v = 0;
    return v + " " + (Math.abs(v) === 1 ? singular : plural);
  };

  /** verbo(1, "está", "estão") -> "está". Para a frase inteira concordar, não só
   *  o substantivo: "1 mudança estão" foi o que o WhatsApp entregou em 29/07. */
  window.verbo = function (n, singular, plural) {
    var v = Number(n);
    return Math.abs(isFinite(v) ? v : 0) === 1 ? singular : plural;
  };
})();
