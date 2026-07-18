-- Ciclo do Relatório de Gestão das transferências especiais (estoque 2020–2024).
-- Prazo do ciclo 2026 (30/06/2026) — Comunicados Transferegov (aviso oficial jun/2026)
-- + IN TCU 93/2024 (multa diária de 1% por pendência no estoque 2020–2024).

INSERT INTO regras_normativas (parametro, regime, valor, base_legal, vigencia_inicio, vigencia_fim) VALUES
('pix_relatorio_gestao_estoque', 'especiais',
 '{"prazo":"2026-06-30","abrange_anos":"2020-2024"}',
 'Comunicado Transferegov (ciclo 2026 do Relatório de Gestão) + IN TCU 93/2024',
 '2026-01-01', '2026-12-31')
ON CONFLICT (parametro, regime, vigencia_inicio) DO NOTHING;
