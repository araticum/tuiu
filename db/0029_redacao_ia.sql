-- Interruptor da redação por IA (etapa B).
--
-- A regra da casa é que a DeepInfra é paga e não roda sem autorização
-- explícita. Aqui há um segundo motivo, mais pesado: mesmo com o texto
-- pseudonimizado (`app.anonimo`), a chamada envia o CORPO do parecer a um
-- processador externo — e o corpo pode identificar por contexto (objeto do
-- convênio, valor exato, número do edital).
--
-- Nasce FALSE. Ligar é ato deliberado e registrado, como todo envio externo
-- deste sistema.
INSERT INTO configuracoes (chave, valor, atualizado_por) VALUES
    ('redacao_ia', 'false', 'migration 0029 — etapa B, so com o gate respondido')
ON CONFLICT (chave) DO NOTHING;
