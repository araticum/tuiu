-- Isolamento por papel + inventário de PII no schema.
--
-- Gate D3 (deny by default): quem entra como `cliente` só enxerga o próprio
-- CNPJ. Papel novo nasce sem alcance; ampliar é ato explícito.
--
-- Os COMMENT com prefixo `pii:` fazem o inventário ser grepável
-- (`grep -r "pii:" db/`), como manda o §3 do PRIVACY.md do Quimera.

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS papel text NOT NULL DEFAULT 'operador';
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS doc_cliente text;

-- operador: vê a carteira toda (é quem opera). cliente: só o próprio doc.
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_papel_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_papel_ck
    CHECK (papel IN ('operador', 'cliente'));

-- A trava mora no BANCO, não só no código: papel 'cliente' sem doc não pode
-- existir, senão o filtro "só o meu" viraria "sem filtro".
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_escopo_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_escopo_ck
    CHECK ((papel = 'operador' AND doc_cliente IS NULL)
        OR (papel = 'cliente'  AND doc_cliente IS NOT NULL));

-- ---------------------------------------------------------------- inventário
COMMENT ON COLUMN usuarios.login         IS 'pii:identificador do operador';
COMMENT ON COLUMN usuarios.nome          IS 'pii:nome';
COMMENT ON COLUMN usuarios.senha_hash    IS 'credencial (scrypt, sal por usuário) — nunca em claro';
COMMENT ON COLUMN sessoes.ip             IS 'pii:ip';
COMMENT ON COLUMN sessoes.agente         IS 'pii:user-agent';
COMMENT ON COLUMN acessos_log.ip         IS 'pii:ip';
COMMENT ON COLUMN acessos_log.login      IS 'pii:identificador do operador';
COMMENT ON COLUMN clientes_pessoas.cpf   IS 'pii:cpf do dirigente (PF) — MROSC';
COMMENT ON COLUMN clientes_pessoas.nome  IS 'pii:nome do dirigente (PF)';
COMMENT ON COLUMN clientes.nome          IS 'razão social; para Empresário Individual equivale a nome de PF';
COMMENT ON COLUMN diario_cliente.texto   IS 'pii:texto livre de atendimento — pode conter dado de PF';

-- D4 (retenção com prazo): sessão e tentativa de acesso não servem para nada
-- depois da janela de auditoria. Sem prazo, viram acervo de IP sem finalidade.
CREATE OR REPLACE VIEW expurgo_pendente AS
    SELECT 'sessoes'     AS tabela, count(*) AS linhas
      FROM sessoes     WHERE expira_em < now() - interval '7 days'
    UNION ALL
    SELECT 'acessos_log' AS tabela, count(*) AS linhas
      FROM acessos_log WHERE quando   < now() - interval '180 days';
