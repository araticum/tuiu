-- Seed das regras normativas (§3 do plano — verificado no DOU 17-18/07/2026).
-- Regra de ouro: valor muda => NOVA LINHA com vigência; jamais UPDATE no valor.

INSERT INTO regras_normativas (parametro, regime, valor, base_legal, vigencia_inicio, vigencia_fim) VALUES
-- Prestação de contas — apresentação (60d) e escada de inadimplência
('prazo_prestacao_contas_apresentacao', 'completo_pc33',    '{"dias":60}',  'PC MGI/MF/CGU 33/2023, art. 96 (confirmado no texto integral)', '2023-09-01', NULL),
('prazo_prestacao_contas_apresentacao', 'legado_pi424',     '{"dias":60}',  'PI 424/2016 (regime legado, ultratividade)',                    '2016-01-01', NULL),
('prazo_notificacao_apos_prazo',        'completo_pc33',    '{"dias":45}',  'PC 33/2023, art. 96, §1º',                                      '2023-09-01', NULL),
('prazo_devolucao_apos_notificacao',    'completo_pc33',    '{"dias":30}',  'PC 33/2023, art. 96, §2º, II',                                  '2023-09-01', NULL),
-- Análise da prestação de contas
('prazo_analise_informatizado',         'completo_pc33',    '{"dias":60,"prorrogavel_por_igual":true,"conta_de":"nota_de_risco"}', 'PC 33/2023, art. 97, I e §1º', '2023-09-01', NULL),
('prazo_analise_convencional',          'completo_pc33',    '{"dias":180,"prorrogavel_por_igual":true,"conta_de":"envio"}',        'PC 33/2023, art. 97, II e §2º','2023-09-01', NULL),
-- Saneamento: O CASO REAL DE VERSIONAMENTO (45d até 14/07/2026; 30d desde 15/07/2026)
('prazo_saneamento_impropriedades',     'completo_pc33',    '{"dias":45}',  'PC 33/2023, art. 97, §3º (redação original)',                   '2023-09-01', '2026-07-14'),
('prazo_saneamento_impropriedades',     'completo_pc33',    '{"dias":30}',  'PC 33/2023, art. 97, §3º (redação da PC 45/2026, DOU 15/07/2026)', '2026-07-15', NULL),
-- Devolução de saldos e registro de recebimento
('prazo_devolucao_saldos',              'completo_pc33',    '{"dias":30}',  'PC 33/2023, art. 95, §1º',                                      '2023-09-01', NULL),
('prazo_registro_recebimento_pc',       'completo_pc33',    '{"dias":15}',  'PC 33/2023, art. 98, §2º',                                      '2023-09-01', NULL),
-- Regimes e cortes
('corte_regime_simplificado',           'geral',            '{"valor":1576882.20}', 'Lei 14.133, art. 184-A + Decreto 12.343/2024',           '2025-01-01', NULL),
('guarda_documental',                   'completo_pc33',    '{"anos":5}',   'PC 33/2023, art. 9º, §2º',                                      '2023-09-01', NULL),
('guarda_documental',                   'legado_pi424',     '{"anos":10}',  'PI 424/2016 (regime legado)',                                   '2016-01-01', NULL),
-- Transferências especiais (Pix)
('pix_multa_diaria_pendencia',          'especiais',        '{"percentual_dia":1}', 'IN TCU 93/2024 (planos/relatórios 2020–2024)',           '2024-01-17', NULL),
('pix_capital_minimo',                  'especiais',        '{"percentual":70}',    'CF, art. 166-A, §5º (EC 105/2019)',                      '2019-12-10', NULL),
('pix_fluxo_avaliacao_plano',           'especiais',        '{"complementacao_dias":30,"parecer_dias":60,"reenvio_dias":30}', 'PC MGI/MF 2/2025, art. 3º', '2025-01-24', NULL),
-- Defeso eleitoral 2026 (eleições gerais 04/10/2026)
('defeso_eleitoral',                    'geral',            '{"inicio":"2026-07-04","fim":"2026-10-04"}', 'Lei 9.504/1997, art. 73, VI, "a"', '2026-07-04', '2026-10-04'),
-- LDO 2026: piso de pagamento de emendas impositivas
('ldo_piso_pagamento_emendas',          'geral',            '{"percentual":65,"ate":"2026-06-30"}', 'LDO 2026 (Lei 15.321/2025)',           '2026-01-01', '2026-12-31')
ON CONFLICT (parametro, regime, vigencia_inicio) DO NOTHING;
