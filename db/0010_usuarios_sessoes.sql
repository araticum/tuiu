-- Autenticação do console. Ele mostra CNPJ, contas, valores e prazos de 50
-- organizações reais — não pode ficar aberto em porta nenhuma.

CREATE TABLE IF NOT EXISTS usuarios (
    login          text PRIMARY KEY,
    nome           text NOT NULL,
    senha_hash     text NOT NULL,   -- scrypt: n$r$p$salt_b64$hash_b64
    ativo          boolean NOT NULL DEFAULT true,
    trocar_senha   boolean NOT NULL DEFAULT false,  -- senha inicial gerada pela máquina
    criado_em      timestamptz NOT NULL DEFAULT now(),
    ultimo_acesso  timestamptz
);

CREATE TABLE IF NOT EXISTS sessoes (
    token      text PRIMARY KEY,
    login      text NOT NULL REFERENCES usuarios(login) ON DELETE CASCADE,
    criada_em  timestamptz NOT NULL DEFAULT now(),
    expira_em  timestamptz NOT NULL,
    ip         text,
    agente     text
);
CREATE INDEX IF NOT EXISTS sessoes_login_idx ON sessoes (login);

-- Toda tentativa, com e sem sucesso. Serve para o freio de força bruta e para
-- saber depois quem entrou (ou tentou).
CREATE TABLE IF NOT EXISTS acessos_log (
    id      serial PRIMARY KEY,
    login   text,
    sucesso boolean NOT NULL,
    motivo  text,
    ip      text,
    quando  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS acessos_log_quando_idx ON acessos_log (quando DESC);
