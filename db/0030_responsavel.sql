-- Atribuição: DE QUEM é o item, decidido antes do trabalho.
--
-- `fila_status` já guardava `operador`, mas isso é PEGADA — quem mexeu por
-- último —, e pegada só existe depois que alguém age. É por isso que a tabela
-- tinha 0 linhas com 757 itens já abertos em `fila_visto`: as pessoas olhavam a
-- mesa, trabalhavam, e não havia nada a marcar antes de terminar.
--
-- Uma mesa de trabalho precisa dizer "isto é seu" ANTES. Sem isso não existe
-- "minha fila", ninguém sabe se um item está coberto ou esquecido, e dois
-- operadores podem tocar o mesmo convênio sem se ver.
--
-- Fica em `fila_status` porque o grão é o mesmo (um item da mesa, pela `chave`)
-- e separar em outra tabela obrigaria join em toda leitura da mesa para
-- responder uma pergunta que é do mesmo objeto.
ALTER TABLE fila_status ADD COLUMN IF NOT EXISTS responsavel   text;
ALTER TABLE fila_status ADD COLUMN IF NOT EXISTS atribuido_em  timestamptz;
ALTER TABLE fila_status ADD COLUMN IF NOT EXISTS atribuido_por text;

-- "o que é meu" é a consulta que a mesa passa a fazer o tempo todo
CREATE INDEX IF NOT EXISTS ix_fila_status_responsavel
    ON fila_status (responsavel) WHERE responsavel IS NOT NULL;

-- `status` continua com o default 'aberto': atribuir NÃO é começar a trabalhar,
-- e forçar 'em_andamento' na atribuição mentiria sobre o andamento.
