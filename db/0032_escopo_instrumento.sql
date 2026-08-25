-- Escopo de trabalho: QUAIS instrumentos a casa acompanha, dentro de cada cliente.
--
-- Queixa do dono (25/08/2026): a notificação diária manda lixo, "fora da cadeia
-- de interesse da fonte". Medido: 37 dos 98 itens da mensagem não estavam na
-- lista de trabalho, e o PRIMEIRO item da mensagem era um deles.
--
-- A causa é uma confusão entre duas coisas parecidas:
--
--   cliente na carteira  ≠  instrumento sob acompanhamento
--
-- O recorte puxa do dump federal TODOS os convênios de cada CNPJ da carteira —
-- e faz bem, porque a ficha do cliente precisa mostrar a vida dele inteira. Mas
-- a mesa e a notificação são a FILA DE TRABALHO, e ali só cabe o que a casa
-- realmente opera. Um cliente com 40 convênios no sistema federal dos quais a
-- casa cuida de 3 estava enchendo a fila com 37.
--
-- Por que TABELA e não uma coluna em `marcos`: o marco é derivado, regerado a
-- cada rodada do motor; o escopo é decisão humana e precisa sobreviver à
-- regeração. E porque o operador tem que poder acrescentar um instrumento novo
-- na segunda-feira sem esperar deploy.
--
-- `ativo=false` em vez de DELETE pela razão de sempre: tirar da fila não pode
-- apagar o registro de que um dia esteve lá.

CREATE TABLE IF NOT EXISTS instrumentos_escopo (
    cnpj        text NOT NULL,
    instrumento text NOT NULL,
    origem      text NOT NULL DEFAULT 'lista',   -- lista | manual
    ativo       boolean NOT NULL DEFAULT true,
    observacao  text,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    criado_por  text,
    PRIMARY KEY (cnpj, instrumento)
);

CREATE INDEX IF NOT EXISTS ix_instrumentos_escopo_ativo
    ON instrumentos_escopo (cnpj) WHERE ativo;
