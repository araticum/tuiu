-- Execução financeira por convênio (F2) — as colunas de dinheiro da planilha
-- "Execução" do Danilo. O detru legado já traz, por convênio ativo,
-- repasse/desembolsado/saldo a devolver/rendimento (84% com desembolso
-- preenchido na carteira de 50); o recorte só narrava em texto. Aqui viram linha
-- consultável para a Mesa mostrar quanto entrou, saiu e falta devolver.
--
-- Só legado nesta leva: o G2 (novo) publica a data do saldo mas quase nunca o
-- valor (armadilha documentada em recorte_ente) — entra quando a fonte melhorar.

CREATE TABLE IF NOT EXISTS execucao_convenio (
    cnpj                      text NOT NULL,
    instrumento               text NOT NULL,          -- NR_CONVENIO
    fonte                     text NOT NULL DEFAULT 'legado',
    situacao                  text,
    vl_global                 numeric,
    vl_repasse                numeric,                -- repasse federal (denominador do %)
    vl_contrapartida          numeric,
    vl_empenhado              numeric,
    vl_desembolsado           numeric,                -- quanto de fato saiu do tesouro
    vl_saldo_reman_tesouro    numeric,                -- a devolver à União
    vl_saldo_reman_convenente numeric,
    vl_rendimento             numeric,                -- rendimento de aplicação (entra na PC)
    vl_saldo_conta            numeric,
    inicio_vigencia           date,
    fim_vigencia              date,
    limite_prestacao          date,
    snapshot                  text,
    atualizado_em             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cnpj, instrumento)
);

CREATE INDEX IF NOT EXISTS execucao_convenio_cnpj ON execucao_convenio (cnpj);

COMMENT ON TABLE execucao_convenio IS
  'Execução financeira por convênio (detru legado): repasse, desembolsado, saldo '
  'a devolver, rendimento. Reposta a cada rodada do pipe (app/execucao.py). '
  'Alimenta a Mesa de trabalho com as colunas de dinheiro da planilha do Danilo.';
