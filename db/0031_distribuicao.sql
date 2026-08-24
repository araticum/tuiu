-- Cota de distribuição: quanto da fila sem dono cabe a cada operador.
--
-- Pedido do dono (24/08/2026): distribuir todos os processos sem responsável,
-- "com possibilidade de ajuste de porcentagem a partir dos responsáveis
-- inseridos na ferramenta".
--
-- A cota mora em TABELA, e não em parâmetro do comando, por três motivos:
--
-- 1. quem opera precisa ajustar sem deploy — férias, entrada e saída de gente,
--    alguém sobrecarregado numa semana;
-- 2. distribuir trabalho entre pessoas é decisão que precisa de RASTRO: quem
--    mudou a cota de quem, quando, de quanto para quanto;
-- 3. a cota tem que sobreviver entre rodadas, senão cada distribuição vira uma
--    negociação nova.
--
-- O percentual é do LOTE SEM DONO, não da carteira inteira. Reequilibrar quem já
-- tem item na mão é outro problema (exige tirar trabalho de alguém que já
-- começou) e não se resolve por acidente numa rotina de distribuição.
--
-- `responsavel` referencia `usuarios.login` por CONTRATO, não por chave
-- estrangeira: `fila_status.responsavel` também não tem, e `fila.atribuir` já
-- recusa quem não é operador ativo. Amarrar aqui obrigaria a apagar cota ao
-- desativar conta, e a cota de quem saiu de férias é justamente o que se quer
-- preservar.

CREATE TABLE IF NOT EXISTS distribuicao_cota (
    responsavel   text PRIMARY KEY,          -- usuarios.login
    percentual    numeric(6,3) NOT NULL DEFAULT 0 CHECK (percentual >= 0 AND percentual <= 100),
    ativo         boolean NOT NULL DEFAULT true,
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_por text
);

-- O rastro. Mesma razão do `configuracoes_log`: mudar quanto trabalho vai para
-- quem é decisão de gestão, e decisão sem histórico vira discussão sem prova.
CREATE TABLE IF NOT EXISTS distribuicao_cota_log (
    id            bigserial PRIMARY KEY,
    responsavel   text NOT NULL,
    de            numeric(6,3),
    para          numeric(6,3),
    quem          text,
    quando        timestamptz NOT NULL DEFAULT now()
);

-- Cada rodada de distribuição, para saber o que foi automático e o que foi mão.
-- Sem isto, "por que este item é meu?" não tem resposta depois de uma semana.
CREATE TABLE IF NOT EXISTS distribuicao_rodada (
    id            bigserial PRIMARY KEY,
    quem          text,
    quando        timestamptz NOT NULL DEFAULT now(),
    itens         integer NOT NULL DEFAULT 0,
    agrupou_por_cliente boolean NOT NULL DEFAULT true,
    detalhe       jsonb                      -- {login: quantidade} do que saiu
);

CREATE INDEX IF NOT EXISTS ix_distribuicao_cota_log_quando
    ON distribuicao_cota_log (quando DESC);
