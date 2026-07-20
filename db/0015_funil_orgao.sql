-- Funil de proposta por órgão — a metade UPSTREAM da inteligência de órgão.
--
-- base_rates_orgao mede o desfecho DEPOIS da celebração (dos ~364k que viraram
-- convênio). Mas a decisão do nosso cliente — terceiro-executor — vem ANTES: a
-- qual órgão levar a proposta. E aí a dispersão é brutal: OSC que protocola na
-- Sec. de Agricultura Familiar é reprovada em ~92%; no Esporte, ~36%. 90 pontos
-- de amplitude, medidos. Ninguém no nicho mostra a odds ANTES de escrever a
-- primeira linha do plano de trabalho.
--
-- Diferença-chave para o desfecho: aqui o regime NOVO (PC 33) TAMBÉM é preditivo
-- — proposta é decidida rápido, então há 86k resolvidas no ciclo atual. O
-- desfecho pós-celebração o novo ainda não tem; o funil, tem. Logo `preditivo`
-- vale por linha (n_resolvidas>=100), e o NOVO é a odds sob a regra de HOJE.

CREATE TABLE IF NOT EXISTS funil_orgao (
    orgao         text NOT NULL,
    regime        text NOT NULL,      -- legado_pi424 | novo_pc33
    n_total       int  NOT NULL,      -- propostas de OSC ao órgão (no regime)
    n_resolvidas  int  NOT NULL,      -- já aprovadas OU reprovadas (não em curso)
    pct_aprovada  numeric,            -- % das resolvidas que aprovaram/celebraram
    pct_reprovada numeric,            -- % das resolvidas reprovadas/rejeitadas
    pct_em_curso  numeric,            -- % do total ainda tramitando
    -- preditivo POR REGIME: o funil tem sinal atual (PC 33), ao contrário do
    -- desfecho. true quando há resolvidas suficientes para a taxa não ser ruído.
    preditivo     boolean NOT NULL DEFAULT false,
    fonte         text NOT NULL DEFAULT 'SICONV (detru)',
    computado_em  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (orgao, regime)
);

COMMENT ON TABLE funil_orgao IS
  'Taxa de aprovação de proposta de OSC por órgão × regime (funil pré-celebração). '
  'Complementa base_rates_orgao (desfecho pós-celebração): junte os dois e o cliente '
  'vê a odds de ponta a ponta — passar no órgão E sobreviver à prestação. O NOVO (PC 33) '
  'é preditivo aqui (proposta é decidida rápido), então é a odds sob a regra vigente.';
