-- Guia de gestão das transferências: acervo oficial + guia próprio, indexado.
--
-- O operador para de adivinhar e passa a consultar a fonte. São 94 PDFs oficiais
-- do Transferegov (gov.br) — e a árvore de pastas de lá JÁ É o pipeline
-- (Cadastro → Atos Preparatórios → Execução → Prestação de Contas), com tutorial
-- separado por PAPEL (convenente = nosso cliente; concedente = o órgão). Guardamos
-- essa estrutura: é o esqueleto da navegação e o filtro que faz a busca acertar.
--
-- BUSCA HÍBRIDA, por decisão de infra: a imagem do banco não tem pgvector, então o
-- vetor mora num `real[]` e o cosseno é feito em Python (corpus pequeno, cabe em
-- memória). Em paralelo, FTS português com stemmer sobre `tuiu_norm` (que é
-- IMMUTABLE, então dá pra gerar a coluna). Fundir os dois recupera mais do que
-- qualquer um sozinho — e o FTS não custa nada.

CREATE TABLE IF NOT EXISTS guia_trechos (
    id          bigserial PRIMARY KEY,
    fonte       text NOT NULL,          -- manual | guia | norma
    modulo      text,                   -- discricionarias | parcerias | especiais | cadastro | perfis | guia
    etapa       text,                   -- a etapa do pipeline (vem da pasta do gov.br)
    papel       text,                   -- convenente | concedente | geral
    documento   text NOT NULL,          -- título do manual/seção
    pagina_ini  int,
    pagina_fim  int,
    arquivo     text,                   -- PDF local, para consulta na íntegra
    url         text,                   -- origem oficial
    texto       text NOT NULL,
    vetor       real[],                 -- embedding local (ONNX); cosseno em Python
    tsv         tsvector GENERATED ALWAYS AS
                (to_tsvector('portuguese', tuiu_norm(texto))) STORED,
    criado_em   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS guia_trechos_tsv ON guia_trechos USING gin (tsv);
CREATE INDEX IF NOT EXISTS guia_trechos_etapa ON guia_trechos (etapa);
CREATE INDEX IF NOT EXISTS guia_trechos_papel ON guia_trechos (papel);

COMMENT ON TABLE guia_trechos IS
  'Trechos indexados do acervo oficial (Transferegov/gov.br) + do guia próprio. '
  'Busca híbrida: `vetor` (embedding local, cosseno em Python — sem pgvector na imagem) '
  '+ `tsv` (FTS português sobre tuiu_norm, acento-insensível). `etapa`/`papel` vêm da '
  'árvore oficial e servem de filtro e de esqueleto do guia.';
