-- O evento passa a carregar a chave que casa com `marcos.instrumento`.
--
-- Até aqui o notificador procurava contexto usando a CHAVE do diff, e ela só
-- coincide com o instrumento do marco em dois dos quatro domínios:
--
--   proposta_g2      chave = id_proposta        marcos.instrumento = id_proposta   ✓
--   convenio_legado  chave = NR_CONVENIO        marcos.instrumento = NR_CONVENIO   ✓
--   parceria_g2      chave = id_parceria        marcos.instrumento = id_proposta   ✗
--   plano_pix        chave = id_plano_acao      marcos.instrumento = codigo        ✗
--
-- Nos dois que não casam o contexto voltava VAZIO — a mensagem saía sem prazo,
-- sem de quem é a bola e sem próximo passo, sem nada indicar que faltou algo.
-- Hoje é latente (todo evento vem do legado), mas o ciclo novo é o futuro da
-- carteira, e o modo de falhar é o mesmo dos outros bugs desta semana: a coisa
-- certa simplesmente deixa de acontecer.
--
-- Guardar a chave no evento (em vez de traduzir na hora de ler) preserva o que
-- o recorte sabia NAQUELE dia: o vínculo parceria->proposta vive no arquivo do
-- snapshot, não no banco.

ALTER TABLE eventos ADD COLUMN IF NOT EXISTS instrumento text;

-- Backfill: nos domínios em que chave já É o instrumento, ela serve.
UPDATE eventos SET instrumento = chave
 WHERE instrumento IS NULL
   AND chave <> '#count'
   AND dominio IN ('convenio_legado', 'proposta_g2');

CREATE INDEX IF NOT EXISTS eventos_instrumento ON eventos (cnpj, instrumento);
