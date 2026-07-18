-- F1.5 — motor de eventos (diff de andamento) + notificações.

-- Estado visto por (ente, domínio, chave): sobrevive a dia pulado; o diff é
-- contra o ÚLTIMO valor conhecido, não contra "o snapshot de ontem".
CREATE TABLE IF NOT EXISTS entidades_estado (
    cnpj        text NOT NULL,
    dominio     text NOT NULL,        -- proposta_g2 | parceria_g2 | plano_pix | convenio_legado | <contador>
    chave       text NOT NULL,        -- id/nº do item; p/ contadores = '#count'
    valor       text,                 -- situação atual, ou o total (contadores)
    snapshot    date NOT NULL,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cnpj, dominio, chave)
);

-- Eventos de mudança emitidos.
CREATE TABLE IF NOT EXISTS eventos (
    id         bigserial PRIMARY KEY,
    cnpj       text NOT NULL,
    ente       text NOT NULL,
    dominio    text NOT NULL,
    chave      text NOT NULL,
    rotulo     text NOT NULL,         -- rótulo humano do item (ex.: "Plano Pix 0903...")
    tipo       text NOT NULL,         -- novo | mudanca | incremento
    de         text,
    para       text,
    snapshot   date NOT NULL,
    criado_em  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eventos_cnpj_id ON eventos (cnpj, id DESC);

-- Quem é notificado, por ente e canal. Vazio = só outbox.
CREATE TABLE IF NOT EXISTS destinatarios (
    id       serial PRIMARY KEY,
    cnpj     text NOT NULL,           -- '*' = todos os entes
    canal    text NOT NULL,           -- whatsapp | webhook
    endereco text NOT NULL,           -- e164 (whatsapp) | URL (webhook)
    ativo    boolean NOT NULL DEFAULT true,
    UNIQUE (cnpj, canal, endereco)
);

-- Log de entrega (idempotência por evento+canal+endereço).
CREATE TABLE IF NOT EXISTS entregas (
    id         bigserial PRIMARY KEY,
    evento_id  bigint NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
    canal      text NOT NULL,         -- outbox | webhook | whatsapp
    endereco   text,
    mensagem   text NOT NULL,
    status     text NOT NULL DEFAULT 'pendente',  -- pendente | enviado | erro
    detalhe    text,
    criado_em  timestamptz NOT NULL DEFAULT now(),
    enviado_em timestamptz,
    UNIQUE (evento_id, canal, endereco)
);
