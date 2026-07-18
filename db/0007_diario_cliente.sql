-- Diário de atendimento por cliente: a memória da operação.
-- O que a casa fez/combinou/protocolou por aquele terceiro, em ordem.

CREATE TABLE IF NOT EXISTS diario_cliente (
    id         bigserial PRIMARY KEY,
    doc_cliente text NOT NULL REFERENCES clientes(doc) ON DELETE CASCADE,
    quando     timestamptz NOT NULL DEFAULT now(),
    autor      text,
    tipo       text NOT NULL DEFAULT 'nota',   -- nota | contato | protocolo | documento | decisao
    texto      text NOT NULL,
    referencia text                            -- instrumento, proposta, chave da fila...
);
CREATE INDEX IF NOT EXISTS diario_cliente_doc ON diario_cliente (doc_cliente, quando DESC);
