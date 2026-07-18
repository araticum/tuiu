-- Camada de OPERAÇÃO (escopo 18/07): o Tuiú é o console com que NÓS operamos
-- o Transferegov de terceiros que receberam verba pública.

-- Carteira de clientes (o terceiro que recebeu a verba).
CREATE TABLE IF NOT EXISTS clientes (
    doc        text PRIMARY KEY,           -- CNPJ (14) — no universo de convênios o recebedor é sempre PJ
    tipo_doc   text NOT NULL DEFAULT 'CNPJ',
    nome       text NOT NULL,
    apelido    text,
    natureza   text,                       -- Associação Privada, Cooperativa, Empresário Individual...
    uf         text,
    municipio  text,
    operador   text,                       -- quem, na casa, responde por este cliente
    ativo      boolean NOT NULL DEFAULT true,
    observacao text,
    criado_em  timestamptz NOT NULL DEFAULT now()
);

-- Pessoas ligadas ao cliente (dirigentes/responsáveis). PF entra AQUI: no MROSC
-- um dirigente impedido contamina a entidade, e CEIS/CNEP listam CPF.
CREATE TABLE IF NOT EXISTS clientes_pessoas (
    id        serial PRIMARY KEY,
    doc_cliente text NOT NULL REFERENCES clientes(doc) ON DELETE CASCADE,
    cpf       text NOT NULL,
    nome      text NOT NULL,
    papel     text,                        -- dirigente, representante legal, responsável técnico...
    ativo     boolean NOT NULL DEFAULT true,
    UNIQUE (doc_cliente, cpf)
);

-- Triagem da fila de trabalho: o operador marca o que já tratou.
-- `chave` é determinística (tipo:cliente:referência) para sobreviver à recarga diária.
CREATE TABLE IF NOT EXISTS fila_status (
    chave         text PRIMARY KEY,
    status        text NOT NULL DEFAULT 'aberto',   -- aberto | em_andamento | resolvido | ignorado
    nota          text,
    operador      text,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);
