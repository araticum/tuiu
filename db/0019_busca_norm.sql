-- Normalização para busca acento-insensível (português).
--
-- ILIKE é sensível a acento: "saude" não casa "SAÚDE", "associacao" não casa
-- "ASSOCIAÇÃO". Numa busca de gestão isso é inaceitável. `tuiu_norm` baixa a
-- caixa e remove os acentos por translate() — sem depender da extensão unaccent
-- (que pode faltar na imagem). IMMUTABLE: dá pra indexar depois se precisar.
CREATE OR REPLACE FUNCTION tuiu_norm(t text) RETURNS text AS $$
  SELECT lower(translate(coalesce(t, ''),
    'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç',
    'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'));
$$ LANGUAGE sql IMMUTABLE;
