-- Base rates regime-aware — o primeiro produto de inteligência sobre o lake.
--
-- "Vencer na inteligência, não no volume": o valor não é ter 18 anos de SICONV,
-- é a probabilidade destilada. E ela É DATADA — cada desfecho carrega o regime
-- que o produziu. Medido: o regime legado (PI 424) tem 69% de desfecho final; o
-- ciclo novo, 2,6% (jovem demais). Logo a previsão vem do legado, e a coluna
-- `regime` diz sob qual lei — um concorrente que agrega cru dá conselho
-- confiante-e-errado sob uma regra morta.
--
-- Tabela pequena (dezenas de órgãos × 2 regimes), COMPUTADA no lake (DuckDB) e
-- carregada aqui. O console cruza pelo órgão do convênio do cliente.

CREATE TABLE IF NOT EXISTS base_rates_orgao (
    orgao               text NOT NULL,
    regime              text NOT NULL,      -- legado_pi424 | novo_pc33
    n                   int  NOT NULL,      -- convênios de OSC na base
    pct_sucesso         numeric,            -- prestação concluída/aprovada
    pct_ressalva        numeric,            -- aprovada COM ressalvas
    pct_morte           numeric,            -- anulado/cancelado/rejeitado/inadimplente/TCE
    pct_em_curso        numeric,            -- ainda sem final
    prestacoes_paradas  int,               -- prestações entregues paradas na análise do órgão
    mediana_dias_parada int,               -- mediana de dias paradas (comportamento do concedente)
    -- flag de confiança: legado = preditivo; novo = amostra insuficiente de finais
    preditivo           boolean NOT NULL DEFAULT false,
    fonte               text NOT NULL DEFAULT 'SICONV (detru)',
    computado_em        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (orgao, regime)
);

COMMENT ON TABLE base_rates_orgao IS
  'Base rates de desfecho por órgão × regime. Regime legado=histórico com finais (preditivo=true); '
  'novo=ciclo atual sem finais suficientes (preditivo=false, só contexto). Coluna regime = o MOAT: '
  'a resposta certa exige saber sob qual lei cada final aconteceu.';
