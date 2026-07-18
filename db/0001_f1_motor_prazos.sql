-- F1 — motor de prazos: regras normativas versionadas, marcos e alertas (outbox).

CREATE TABLE IF NOT EXISTS regras_normativas (
    id              serial PRIMARY KEY,
    parametro       text NOT NULL,          -- ex.: prazo_prestacao_contas_apresentacao
    regime          text NOT NULL,          -- legado_pi424 | completo_pc33 | simplificado_pc28 | especiais | geral
    valor           jsonb NOT NULL,         -- {"dias":60} | {"percentual":70} | {"inicio":"...","fim":"..."}
    base_legal      text NOT NULL,
    vigencia_inicio date NOT NULL,
    vigencia_fim    date,                   -- NULL = vigente; NUNCA sobrescrever: nova redação = nova linha
    criado_em       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (parametro, regime, vigencia_inicio)
);

CREATE TABLE IF NOT EXISTS marcos (
    id            serial PRIMARY KEY,
    cnpj          text NOT NULL,
    ente          text NOT NULL,
    fonte         text NOT NULL,            -- legado | g2 | especiais | geral
    instrumento   text,                     -- NR_CONVENIO / cd_parceria / codigo_plano_acao
    tipo          text NOT NULL,            -- prestacao_contas | fim_vigencia | impedimento_pix | defeso_eleitoral
    data_limite   date,                     -- NULL = ação imediata (sem data)
    descricao     text NOT NULL,
    base_legal    text NOT NULL,
    farol         text NOT NULL,            -- vencido | atencao | ok | acao_imediata
    detalhes      jsonb,
    snapshot      date NOT NULL,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS marcos_chave ON marcos
    (cnpj, fonte, tipo, COALESCE(instrumento, ''), COALESCE(data_limite, '0001-01-01'::date));

CREATE TABLE IF NOT EXISTS alertas (
    id         serial PRIMARY KEY,
    marco_id   int NOT NULL REFERENCES marcos(id) ON DELETE CASCADE,
    gatilho    text NOT NULL,               -- vencido | T-1 | T-7 | T-30
    canal      text NOT NULL DEFAULT 'outbox',
    mensagem   text NOT NULL,
    criado_em  timestamptz NOT NULL DEFAULT now(),
    enviado_em timestamptz,
    UNIQUE (marco_id, gatilho)
);
