-- Checklist de dossiê da prestação de contas (F3) — o "% de dossiê" da planilha
-- do Danilo. A fonte (Transferegov) NÃO diz quais documentos a OSC já reuniu:
-- é rastreio MANUAL do operador. Aqui cada item do dossiê vira uma marca por
-- convênio; o % = itens feitos / total. Sem Sargaço (decisão do dono, 18/07): é
-- status, não upload — o arquivo físico segue no dossiê de pasta (app/dossie.py).

CREATE TABLE IF NOT EXISTS dossie_checklist (
    cnpj        text NOT NULL,
    instrumento text NOT NULL,       -- NR_CONVENIO
    item        text NOT NULL,       -- slug do item (ITENS_DOSSIE em app/dossie.py)
    feito       boolean NOT NULL DEFAULT false,
    nota        text,
    marcado_por text,
    marcado_em  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cnpj, instrumento, item)
);

CREATE INDEX IF NOT EXISTS dossie_checklist_conv ON dossie_checklist (cnpj, instrumento);

COMMENT ON TABLE dossie_checklist IS
  'Marcação manual do dossiê de PC por convênio (o "% dossiê" da planilha do '
  'Danilo). Só linhas marcadas existem; o catálogo de itens mora no código.';
