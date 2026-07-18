# API g2 — módulo Gestão de Parcerias (Transferências Discricionárias e Legais)

> Levantamento e extração verificados ao vivo em **17/07/2026**. Fonte primária do Tuiú (F0).
> Base: `https://api-publica.transferegov.gestao.gov.br/parcerias` · Swagger: `/parcerias/docs` · Spec: `/parcerias/openapi.json`
> Sem chave, só GET, dados D-1 (carga ~09h — conferir `/data-atualizacao`).

## O que é (e o que NÃO é)

É a API de dados abertos do **módulo novo de Gestão de Parcerias** do Transferegov — o ciclo
Discricionárias e Legais reformulado (propostas/parcerias a partir de ~2025, incl. instrumentos
FAF Saúde com beneficiário de emenda). **Não contém o estoque histórico SICONV (2008→)** — esse
segue nos CSVs diários `repositorio.dados.gov.br/seges/detru/` (espelho `/downloads` da g2).
A API g1 (`api.transferegov.gestao.gov.br`) não tem Discricionárias (só especiais/TED/FaF) e
**desliga 31/08/2026** — zero dependência dela.

## Regras de acesso (medidas ao vivo)

| Regra | Valor |
|---|---|
| Autenticação | nenhuma |
| Métodos | GET apenas |
| Paginação | `pagina` (1-based) + `tamanho_da_pagina` — **cap 200** (422 acima) |
| Envelope | `{data, total_pages, total_items, page_number, page_size}` |
| Filtros | todos os parâmetros opcionais; igualdade simples, nomes = colunas |
| Frescor | `/data-atualizacao` → `{data_ultima_atualizacao}` (singleton, sem envelope) |
| Erros | 422 para parâmetro inválido; 307 redirect em `/parcerias` → `/parcerias/docs` |

## As 16 rotas — volumes de 17/07/2026 (~2,34 mi registros)

| Rota | PK | Liga em | total_items | Observações |
|---|---|---|---:|---|
| `/programa` | `id_programa` | — | 176 | embute `ufs_habilitadas`, `programa_atende_a`, `categorias_despesa`, `resultados_esperados`, `indicadores_programa` |
| `/proposta` | `id_proposta` | `id_programa` | 87.776 | **hub do recorte por ente**: `cnpj_ente_recebedor`, `cd_ibge_recebedor`; embute `intervenientes_proposta`, `categorias_despesa_proposta` |
| `/meta-proposta` | `id_meta_proposta` | `id_proposta` | 98.681 | embute `etapas_proposta[]` (etapas com datas) |
| `/item-proposta` | `id_item_proposta` | `id_etapa_proposta` | 404.323 | liga na ETAPA (não direto na proposta); embute `classificacao_despesa{}` |
| `/cronograma-desembolso` | `id_proposta_cronograma_item` | `id_proposta` | 104.302 | |
| `/parceria` | `id_parceria` | `id_proposta` | 87.776 | 1:1 com proposta; `cd_parceria` (ex. 202500037062), `nu_externo`, SEI, assinatura, publicação DOU (`publicacoes_parceria[]`) |
| `/parceria-conta` | `id_parceria_conta` | `id_parceria` | 89.568 | conta bancária específica (banco, agência, saldo CC/investimento, BB Ágil); embute `classificacoes_ingresso[]` |
| `/analise-proposta` | `id_analise_proposta` | `id_proposta` | 85.421 | fase, resultado, `ds_parecer`, `dh_analise_proposta`; embute `tipos_analise[]` |
| `/proposta-resultado-indicador` | `id_proposta_resultado_indicador` | `id_proposta` | 11.450 | |
| `/distribuicao-recurso-proposta` | `id_distribuicao_recurso_proposta` | `id_proposta` | 83.534 | emenda: nº, parlamentar, tipo, GND, valor |
| `/empenho-parceria` | `id_empenho_parceria` | `id_parceria` | 68.443 | NE SIAFI: minuta, situação, favorecido, valores |
| `/documento-habil` | `id_documento_habil` | `id_parceria` | 50.575 | DH (tp TF etc.), credor, NE associada |
| `/ordem-pagamento` | `id_op` | `id_documento_habil` | 50.430 | OP + **ordem bancária** (nº/data) — fecha o fluxo NE→DH→OP→OB |
| `/extrato-bancario` | `id_extrato_bancario` | `id_parceria_conta` | 1.035.997 | lançamentos da conta (crédito/débito, tipo operação, contraparte) |
| `/beneficiario_emenda_parlamentar` | `id_beneficiario_emenda_parlamentar_programa` | `id_programa` | 77.740 | beneficiário indicado por emenda: CNPJ, parlamentar, nº emenda, GND3/GND4, valores; embute `indicacoes_beneficiario[]` |

`/data-atualizacao` é a 16ª rota (singleton de frescor).

### Grafo de encadeamento

```
programa ─┬─< proposta ─┬─< meta-proposta ──< etapas_proposta[] <── item-proposta
          │             ├─< cronograma-desembolso
          │             ├─< analise-proposta
          │             ├─< proposta-resultado-indicador
          │             ├─< distribuicao-recurso-proposta
          │             └── parceria (1:1) ─┬─< parceria-conta ──< extrato-bancario
          │                                 ├─< empenho-parceria
          │                                 └─< documento-habil ──< ordem-pagamento
          └─< beneficiario_emenda_parlamentar
```

### Recorte por ente (padrão F0)

1. `proposta?cnpj_ente_recebedor=<CNPJ>` (ou `cd_ibge_recebedor=<IBGE>`) → `id_proposta[]`, `id_programa[]`
2. Filhas de proposta por `id_proposta`; `parceria?id_proposta=` → `id_parceria[]`
3. Filhas de parceria por `id_parceria`; contas → `extrato-bancario?id_parceria_conta=`; DH → `ordem-pagamento?id_documento_habil=`
4. `beneficiario_emenda_parlamentar?nr_cnpj_beneficiario_emenda=<CNPJ>` (radar de emendas por ente)

## Gotchas verificados

- **Resposta real ≠ OpenAPI**: as rotas devolvem campos além do spec (ex.: `parceria.nu_externo`,
  `parceria-conta.id_conta_gf`/saldos CC+investimento, `analise-proposta.ds_parecer`,
  `beneficiario….vl_gnd3/vl_gnd4/vl_total_emenda`) e sub-objetos aninhados (as 28 tabelas do
  modelo oficial achatadas em 16 rotas). Tratar o dado real como fonte da verdade.
- Booleanos `sn_*` chegam como **0/1 inteiro** (spec diz boolean).
- Datas: `YYYY-MM-DD` ou `YYYY-MM-DDTHH:MM:SS[.ffffff]`, sem timezone.
- `total_items` estável ao longo do dia (carga única ~09h); ainda assim o extrator confere
  `/data-atualizacao` antes/depois e valida linhas × `total_items` por rota.
- **LGPD** (gate `D:\Quimera\PRIVACY.md`): a API já mascara CPF no extrato
  (`***54415***`), mas expõe **nome completo de PF** beneficiária de lançamento e dados
  bancários de executores. No produto: minimizar/mascarar; dump bruto não sai do backend.
- Modelo de dados oficial (SchemaSpy, 28 tabelas): zip `modelo_dados_api_parcerias.zip` na
  página raiz da API (`gov.br/transferegov/...paineis-gerenciais/arquivos/`).
- Spec congelado neste repo: [`openapi-parcerias-2026-07-17.json`](openapi-parcerias-2026-07-17.json).

## Extrator

[`ingest/transferegov_g2/g2_parcerias.py`](../ingest/transferegov_g2/g2_parcerias.py) — stdlib pura, paginação com
4 workers, retry/backoff (429/5xx), saída JSONL.gz por rota em `data/parcerias/<data>/` +
`_manifest.json` (linhas × total_items, snapshot estável, duração, filtros).

```powershell
# dump completo (~2,34 mi registros, ~12 min)
D:\venvs\flow\Scripts\python.exe ingest\transferegov_g2\g2_parcerias.py

# recorte por ente
python ingest\transferegov_g2\g2_parcerias.py --rotas proposta --filtro cnpj_ente_recebedor=11140541000131

# amostra rápida
python ingest\transferegov_g2\g2_parcerias.py --paginas-max 2
```

## Módulos irmãos da g2 (fora deste levantamento)

`/especiais` (emendas Pix — 21 rotas, mesmo padrão), `/fundoafundo`, `/downloads` (espelho dos
CSVs detru). O roadmap oficial da g2 para Discricionárias: Atos Preparatórios jul–out/2026 →
Instrumentos nov/2026–fev/2027 → Execução Financeira mar–jun/2027 → Obras jul–out/2027 — ou
seja, esta API ainda vai ganhar rotas; revisitar a cada trimestre.
