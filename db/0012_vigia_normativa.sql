-- Vigília normativa: o que saiu no DOU e pode mexer nas nossas regras.
--
-- O produto vende prazo com base legal CITADA. As portarias conjuntas mudam a
-- cada trimestre (4 alterações na PC 33 desde 2023) e, até aqui, quem percebia
-- a mudança era uma pesquisa manual — a PC 45/2026 e a 46/2026 foram pegas
-- assim. Regra desatualizada não dá erro: dá resposta errada com ar de certa.

CREATE TABLE IF NOT EXISTS normas_vistas (
    id            serial PRIMARY KEY,
    fonte         text NOT NULL DEFAULT 'DOU',
    secao         text,                    -- DO1, DO1E (extra)…
    publicado_em  date NOT NULL,
    identifica    text NOT NULL,           -- "Portaria Conjunta MGI/MF/CGU Nº 45, DE 10 DE julho DE 2026"
    orgao         text,
    ementa        text,
    termos        text[] NOT NULL DEFAULT '{}',  -- o que casou (por que veio para nós)
    visto_em      timestamptz NOT NULL DEFAULT now(),
    -- Detectar não basta: alguém tem que dizer se mexe em `regras_normativas`.
    -- Enquanto `tratada` for false, a norma fica pendurada no console.
    tratada       boolean NOT NULL DEFAULT false,
    tratada_em    timestamptz,
    tratada_por   text,
    nota          text,
    UNIQUE (fonte, publicado_em, identifica)
);

CREATE INDEX IF NOT EXISTS normas_vistas_pendentes_idx
    ON normas_vistas (publicado_em DESC) WHERE NOT tratada;

-- Até onde a varredura já chegou, para não rebaixar o DOU inteiro todo dia.
CREATE TABLE IF NOT EXISTS vigia_marcador (
    fonte        text PRIMARY KEY,
    ate          date NOT NULL,
    atualizado_em timestamptz NOT NULL DEFAULT now()
);
