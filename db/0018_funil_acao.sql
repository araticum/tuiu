-- Funil por AÇÃO ORÇAMENTÁRIA — a granularidade que o órgão esconde.
--
-- Medido: DENTRO de um órgão as ações variam até 96 pontos de aprovação
-- (Agricultura vai de 0% a 100% conforme a ação; Esporte 0–99; Cultura 5–100).
-- O órgão é grosso demais nos casos mistos — e é justamente onde o cliente mais
-- precisa de conselho. A ação é o que ele de fato escolhe ao montar a proposta.
--
-- Chave = `acao_orcamentaria` (código do orçamento): ASCII limpa, 100%
-- preenchida e ESTÁVEL entre anos (recorre, média 2 anos, até 18) — ao contrário
-- do cod_programa (anual) e do nome (mojibake nos vintages do detru). O nome
-- fica só como rótulo, higienizado no carregamento.
--
-- ⚠️ A tabela `programa` do lake vem multiplicada (~405×) e uma proposta pode
-- ligar a mais de um programa: por isso o motor DEDUP o programa e conta
-- id_proposta DISTINTO — senão o número infla ordens de grandeza.

CREATE TABLE IF NOT EXISTS funil_acao (
    orgao         text NOT NULL,
    acao          text NOT NULL,      -- código da ação orçamentária (chave estável)
    nome          text,               -- rótulo (nome de programa representativo, limpo)
    regime        text NOT NULL,      -- legado_pi424 | novo_pc33
    n_total       int  NOT NULL,      -- propostas de OSC distintas na (órgão, ação, regime)
    n_resolvidas  int  NOT NULL,
    pct_aprovada  numeric,
    pct_reprovada numeric,
    preditivo     boolean NOT NULL DEFAULT false,
    fonte         text NOT NULL DEFAULT 'SICONV (detru)',
    computado_em  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (orgao, acao, regime)
);

COMMENT ON TABLE funil_acao IS
  'Taxa de aprovação de proposta de OSC por órgão × AÇÃO orçamentária × regime — '
  'o drill-down do funil_orgao onde o órgão é grosso demais (amplitude intra-órgão '
  'mediana ~54 pts). Chave estável = acao_orcamentaria; conta proposta DISTINTA '
  '(a tabela programa do lake é multiplicada). Novo (PC 33) é preditivo, como no funil.';
