-- Papel LEITOR: só-leitura. Vê a carteira inteira como um operador, mas NÃO
-- edita nada (a barreira de escrita fica no middleware). Útil para quem precisa
-- acompanhar sem poder mexer (sócio, auditor, stakeholder).
--
-- Como operador, o leitor não tem doc_cliente (enxerga tudo). O escopo real
-- (o que pode ESCREVER) é zero — garantido no código, não no banco.

ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_papel_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_papel_ck
    CHECK (papel IN ('operador', 'cliente', 'leitor'));

ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_escopo_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_escopo_ck
    CHECK ((papel = 'operador' AND doc_cliente IS NULL)
        OR (papel = 'leitor'   AND doc_cliente IS NULL)
        OR (papel = 'cliente'  AND doc_cliente IS NOT NULL));
