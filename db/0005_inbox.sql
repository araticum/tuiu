-- F1.6 — inbox parser: eventos vindos de e-mail de notificação do Transferegov.
-- Reusa a tabela eventos (fonte='inbox') → flui pelo mesmo notificador.

ALTER TABLE eventos ADD COLUMN IF NOT EXISTS origem  text  NOT NULL DEFAULT 'diff';  -- diff | inbox
ALTER TABLE eventos ADD COLUMN IF NOT EXISTS detalhe jsonb;                           -- remetente, assunto, prazo, links_removidos

-- Idempotência do inbox por Message-ID (a chave do evento inbox = message-id).
CREATE UNIQUE INDEX IF NOT EXISTS eventos_inbox_msgid
    ON eventos (chave) WHERE origem = 'inbox';

-- Mapa opcional: endereço que reencaminha -> CNPJ do ente (quando o corpo não traz CNPJ).
CREATE TABLE IF NOT EXISTS inbox_origem (
    id         serial PRIMARY KEY,
    reencaminhador text NOT NULL,   -- e-mail (To/Delivered-To/Envelope) que identifica o tenant
    cnpj       text NOT NULL,
    ativo      boolean NOT NULL DEFAULT true,
    UNIQUE (reencaminhador, cnpj)
);
