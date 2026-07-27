-- Webhook do WhatsApp Cloud API — o que CHEGA da Meta.
--
-- Duas perguntas que hoje não têm resposta: "quem escreveu para o número?" e
-- "a janela de 24h está aberta?". No Cloud API a entrada só existe por webhook
-- push — não há endpoint para consultar histórico —, então sem esta tabela a
-- informação simplesmente se perde.
--
-- 🔒 MINIMIZAÇÃO POR ESTRUTURA: **não existe coluna de conteúdo de mensagem.**
-- Não é política escrita num doc que alguém esquece: o texto não tem onde ser
-- gravado, então não vaza, não aparece em backup e não precisa de expurgo de
-- conteúdo. As duas perguntas acima se respondem só com metadado.
--
-- Escopo atual (decisão do dono, 27/07/2026): destinatário é a EQUIPE. Ao
-- expandir para CLIENTE, passa pelo gate do PRIVACY.md §2 antes — a partir daí
-- o número de terceiro que escreve é dado pessoal de titular que não é nosso
-- operador.

CREATE TABLE IF NOT EXISTS wpp_entrada (
    id          bigserial PRIMARY KEY,
    tipo        text NOT NULL,          -- mensagem (entrada) | status (recibo do que enviamos)
    numero      text NOT NULL,          -- E.164 do contato, sem '+'
    wamid       text,                   -- id da mensagem na Meta
    status      text,                   -- sent | delivered | read | failed (só em tipo='status')
    erro        text,                   -- motivo, quando status='failed'
    carimbo     timestamptz,            -- horário informado pela Meta
    recebido_em timestamptz NOT NULL DEFAULT now()
);

-- a consulta quente é "última entrada deste número" (janela de 24h)
CREATE INDEX IF NOT EXISTS wpp_entrada_numero ON wpp_entrada (numero, recebido_em DESC);
-- a Meta reentrega o mesmo evento quando não recebe 200; sem isto a janela e a
-- contagem de recibos ficariam infladas por retentativa
CREATE UNIQUE INDEX IF NOT EXISTS wpp_entrada_unica
    ON wpp_entrada (tipo, wamid, COALESCE(status, '')) WHERE wamid IS NOT NULL;
