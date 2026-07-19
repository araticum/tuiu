-- Trocar o próprio login.
--
-- `usuarios.login` é chave primária e `sessoes.login` aponta para ela sem
-- ON UPDATE — um UPDATE no login quebraria com violação de FK. Cascateia.
--
-- `acessos_log.login` NÃO tem FK de propósito e NÃO é reescrito: ele registra o
-- que aconteceu NA ÉPOCA. Renomear o histórico apagaria a trilha de quem entrou
-- com qual identidade. A própria troca entra no log como evento, ligando os dois
-- nomes.

ALTER TABLE sessoes DROP CONSTRAINT IF EXISTS sessoes_login_fkey;
ALTER TABLE sessoes ADD CONSTRAINT sessoes_login_fkey
    FOREIGN KEY (login) REFERENCES usuarios(login) ON UPDATE CASCADE ON DELETE CASCADE;

-- Formato do login: minúsculo, sem espaço, 3–32. Trava no banco para não
-- depender de a validação do código ser lembrada em todo caminho de escrita.
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_login_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_login_ck
    CHECK (login ~ '^[a-z0-9][a-z0-9._-]{2,31}$');
