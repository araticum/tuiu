-- Latência de análise do concedente por órgão — a 3ª face da inteligência.
--
-- art. 97 da PC 33/2023 dá ao CONCEDENTE 60 dias (informatizado) para analisar a
-- proposta. Medido por pares de evento (enviada->decisão), o ciclo NOVO já
-- estoura o próprio prazo na mediana: 16 órgãos, mediana das medianas ~80 dias;
-- Assistência 139d com 82% acima de 60d; e Educação em 3d prova que a dispersão
-- é real (não artefato). É o número que arma o cliente: pressionar o concedente
-- citando o artigo, com o histórico do órgão na mão.
--
-- Regime importa: o limite do art.97 só existe no NOVO (PC 33). No legado não
-- havia prazo — a latência lá é contexto (e é ainda maior). Por isso
-- `limite_legal` só é preenchido no novo.

CREATE TABLE IF NOT EXISTS latencia_orgao (
    orgao             text NOT NULL,
    regime            text NOT NULL,      -- legado_pi424 | novo_pc33
    n                 int  NOT NULL,      -- propostas de OSC com par enviada->decisão
    mediana_dias      int,                -- dias medianos até a decisão
    p90_dias          int,                -- cauda: 90% decidem em até isto
    pct_acima_limite  numeric,            -- % que passou de 60 dias (art.97 informatizado)
    -- 60 no novo (art.97 vale); NULL no legado (não havia prazo legal à época)
    limite_legal      int,
    preditivo         boolean NOT NULL DEFAULT false,
    fonte             text NOT NULL DEFAULT 'SICONV (detru)',
    computado_em      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (orgao, regime)
);

COMMENT ON TABLE latencia_orgao IS
  'Tempo real de análise da proposta pelo concedente, por órgão × regime (pares '
  'de evento enviada->decisão). No NOVO (PC 33) o art.97 dá 60 dias — a maioria '
  'dos órgãos estoura na mediana; pct_acima_limite é a munição para cobrar via art.97.';
