-- Produtividade da fila: sem saber QUANDO um item apareceu, não há como medir
-- tempo de resolução. `fila_status` só guarda a última mexida.

CREATE TABLE IF NOT EXISTS fila_visto (
    chave        text PRIMARY KEY,
    cliente      text,
    tipo         text,
    urgencia     text,
    primeira_vez timestamptz NOT NULL DEFAULT now(),
    ultima_vez   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fila_visto_cliente ON fila_visto (cliente, primeira_vez);

-- Arquivo dos relatórios entregues (o que foi mandado, quando, e o conteúdo).
CREATE TABLE IF NOT EXISTS relatorios_entregues (
    id         bigserial PRIMARY KEY,
    doc_cliente text NOT NULL,
    competencia text NOT NULL,          -- AAAA-MM
    dias        int NOT NULL,
    gerado_em  timestamptz NOT NULL DEFAULT now(),
    caminho    text,
    resumo     jsonb,
    UNIQUE (doc_cliente, competencia)
);
