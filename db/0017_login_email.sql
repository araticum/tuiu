-- Login em formato e-mail (pedro@araticum.net), além do usuário simples.
--
-- O console vai ao ar por túnel e o dono entra por e-mail; o '@' não cabia na
-- regra do 0013. Amplia SÓ o conjunto de caracteres (adiciona '@'), mantendo
-- todo o resto: minúsculo, começa por alfanumérico, 3–32 caracteres, sem
-- espaço nem acento. É um superset — nada que era válido deixa de ser.
ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS usuarios_login_ck;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_login_ck
    CHECK (login ~ '^[a-z0-9][a-z0-9._@-]{2,31}$');
