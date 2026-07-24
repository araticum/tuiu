-- Histórico do chat do guia — toda pergunta e resposta ficam gravadas.
--
-- Três usos: AUDITORIA (o que foi perguntado e o que o modelo respondeu, com a
-- base legal citada — num produto que orienta gestão de dinheiro público, o
-- registro importa); INTELIGÊNCIA DE PRODUTO (o que os clientes mais perguntam
-- revela a dor e a próxima feature); e CUSTO (tokens por pergunta, cacheados ou
-- não). Guarda as fontes citadas (compactas, sem o texto do trecho) para rastrear
-- de onde veio a resposta.

CREATE TABLE IF NOT EXISTS guia_historico (
    id               bigserial PRIMARY KEY,
    quando           timestamptz NOT NULL DEFAULT now(),
    usuario          text,               -- login de quem perguntou
    papel            text,               -- operador | cliente
    doc_cliente      text,               -- CNPJ, quando quem pergunta é cliente
    pergunta         text NOT NULL,
    resposta         text,               -- gerada (NULL se erro/sem chave)
    modelo           text,
    fontes           jsonb,              -- documento/etapa/página citados (sem o texto)
    tokens_entrada   int,
    tokens_cacheados int,
    tokens_saida     int,
    erro             text
);

CREATE INDEX IF NOT EXISTS guia_historico_quando ON guia_historico (quando DESC);
CREATE INDEX IF NOT EXISTS guia_historico_usuario ON guia_historico (usuario, quando DESC);

COMMENT ON TABLE guia_historico IS
  'Histórico do chat do guia: toda pergunta+resposta, com autor, fontes citadas e '
  'tokens. Operador vê tudo; cliente vê o seu. Auditoria + inteligência de produto + custo.';
