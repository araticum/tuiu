# Catálogo de dados — Transferências Discricionárias e Legais

Mapa das fontes públicas úteis ao Tuiú, o que já temos e o que falta. Levantado
em 19/07/2026. Serve para decidir o que ingerir e para não redescobrir fonte a
cada sessão.

**Onde mora o granel:** `/mnt/dados-gov/transferegov-lake/` no araticum (disco de
3,7 TB). 🔴 **Nunca** na raiz de 44 GB — lá vive o `veredas` de produção, e o
volume do `tuiu-db` também; encher a raiz derruba prod.

---

## 1. As duas naturezas do dado

O Transferegov tem **dois ciclos** que não se sobrepõem, e todo o resto decorre
disso:

| | ciclo NOVO (g2) | estoque LEGADO (SICONV) |
|---|---|---|
| fonte | API `api-publica` (JSON) | CSVs diários do `detru` (dados.gov.br) |
| cobre | instrumentos ~2025+ | 2008 → hoje |
| forma | 37 rotas REST paginadas | 53 tabelas relacionais |
| na carteira | 6 de 50 clientes | ~todos |
| execução financeira plena | só em 2027 | completa |

Regra prática: **o presente e o futuro estão na g2; a história e o volume, no
SICONV.** Um banco útil precisa dos dois.

---

## 2. API g2 — `api-publica.transferegov.gestao.gov.br`

Spec viva em `{modulo}/openapi.json`. Paginação 200/página, envelope
`total_items`, `data-atualizacao` diária ~09h. Extrator: `g2_parcerias.py`
(`--modulo parcerias|especiais`, descobre rotas do openapi).

### 2.1 `/parcerias` — 16 rotas (Discricionárias/Legais do ciclo novo)

`programa · proposta · meta-proposta · item-proposta · cronograma-desembolso ·
parceria · parceria-conta · analise-proposta · proposta-resultado-indicador ·
distribuicao-recurso-proposta · empenho-parceria · documento-habil ·
ordem-pagamento · extrato-bancario · beneficiario_emenda_parlamentar ·
data-atualizacao`

**Temos:** dump nacional de 17/07 no laptop (`data/parcerias/2026-07-17/`,
2,3 mi linhas, 164 MB, validado disco×API = 0 divergência). ⚠️ 2 dias velho.

### 2.2 `/especiais` — 21 rotas (transferências ESPECIAIS / emenda Pix)

`planos_acao_especiais · planos_trabalho_especiais · relatorios_gestao_especiais
· relatorios_gestao_novos_especiais · beneficiarios_especiais · empenhos_especiais
· executores_especiais · finalidade_especiais · programas_especiais ·
ordens_pagamentos_ordens_bancarias_especiais · gestao_financeira_lancamentos_especiais
· gestao_financeira_subtransacoes_especiais · saldo_conta_gestao_financeira_especiais
· documentos_habeis_especiais · meta_especiais · orgaos_analises_pendentes_especiais
· planos_acao_historico_especiais · planos_trabalho_historico ·
plano_trabalho_analise_historico_especiais · planos_trabalho_analises_especiais ·
data-atualizacao`

Volume (amostra): planos_acao 57.827 · planos_trabalho 56.416 · empenhos 60.322 ·
executores 57.374 · **gestao_financeira_lancamentos 715.266** · relatorios_gestao
5.362. ⚠️ **Pix é do ENTE** (art. 166-A) — fora do núcleo do cliente OSC, mas é o
universo de emenda parlamentar, útil para radar e contexto.

**Temos:** nada nacional (só recorte por cliente na cadeia). **Baixando agora**
→ `/mnt/dados-gov/transferegov-lake/g2/especiais/`.

---

## 3. Estoque SICONV — CSVs `detru`

`repositorio.dados.gov.br/seges/detru/` — **55 arquivos, 6,70 GB**, carga diária
~06h30. UTF-8-BOM, `;`. Modelo relacional em `modelo_dados_siconv.zip`
(SchemaSpy, **53 tabelas**; hubs: `convenio` 40 col, `proposta` 36 col).

**`siconv.zip` (3,34 GB) é o BUNDLE de todas as ~50 tabelas** — baixar ele
sozinho traz o estoque inteiro, sem precisar dos 55 avulsos. **Baixando agora**
→ `/mnt/dados-gov/transferegov-lake/detru/`.

### Tabelas por família (as que importam para discricionárias/legais)

| família | tabelas |
|---|---|
| **núcleo** | proposta, convenio, programa, proponentes, consorcios |
| **financeiro** | empenho, desembolso, pagamento, plano_aplicacao_detalhado, cronograma_desembolso, ingresso_contrapartida, obtv_convenente, pagamento_tributo |
| **licitação/contrato** | licitacao, itens_licitacao, dl (dispensa/inexig.), itens_dl, contrato |
| **cronograma físico** | meta_crono_fisico, etapa_crono_fisico |
| **alterações** | termo_aditivo, prorroga_oficio, solicitacao_alteracao, solicitacao_ajuste_pt |
| **emenda** | emenda, apoiadores_emendas_programas |
| **histórico** | historico_situacao ✅, historico_projeto_basico |
| **obras/CIPI** | contrato_cipi, empenho_cipi, execucao_fisica_cipi, coordenadas_obra, acomp_obras |
| **PAC (seleção)** | proposta_selecao_pac, resposta_selecao_pac, pergunta_selecao_pac |
| **indicadores** | prop_inst_indicadores_estados, _municipios, proposta_resultado_indicador |

**Tínhamos só 3** (convenio, proposta, historico_situacao) — o bundle traz o resto.

---

## 4. Regularidade e sanção — Portal da Transparência (CGU)

`api.portaldatransparencia.gov.br/api-de-dados` — exige chave (no cofre). Não é
granel: consulta por documento.

- **CEPIM** — entidades privadas impedidas de celebrar (motivo típico: não
  prestou contas). É o que trava um TERCEIRO.
- **CEIS** — inidôneas/suspensas de licitar.
- **CNEP** — punidas pela Lei 12.846.
- **/convenios** — carrega o pré-SICONV (SIAFI 1997–2007), que o detru não tem.

⚠️ Armadilha 5: CEIS/CNEP ignoram filtro desconhecido e devolvem 15 sanções
alheias — só `codigoSancionado`/`nomeSancionado` filtram; reconferir doc de cada
registro. **Já integrado** na cadeia (`coletar_regularidade.py`).

---

## 5. Norma — DOU via INLABS

`inlabs.in.gov.br` (Imprensa Nacional, XML). **Já integrado** (`vigia_dou.py`):
detecta portaria/IN que mexe nas regras e enfileira para avaliação. Fonte
instável (502 frequente) → elo não-essencial.

---

## 6. Quadro societário — Receita (dado aberto)

BrasilAPI / MinhaReceita: QSA (sócios/dirigentes) por CNPJ. **Já integrado**
(`dirigentes.py`) — CPF vem mascarado, checagem de sanção por nome. 84 dirigentes
na carteira.

---

## 7. O que fica de fora (e por quê)

- **CAUC** (regularidade do ENTE) — é do ente, não do terceiro. Captcha-gated.
- **Emendas parlamentares** (portal próprio) — o essencial já vem em
  `beneficiario_emenda_parlamentar` (g2) e `emenda` (SICONV).
- **TCU / acórdãos** — relevante para jurisprudência de prestação de contas, mas
  é pesquisa pontual, não base. Candidato a fase futura.
- **SIOP** (orçamento) — a dotação vem via programa/emenda; SIOP seria
  aprofundamento, não base.

---

## 8. Inventário — o que temos × o que falta (19/07/2026)

| fonte | temos | falta |
|---|---|---|
| g2 /parcerias nacional | ✅ 07-17 (laptop) | atualizar |
| g2 /especiais nacional | — | ⏳ baixando |
| SICONV completo (bundle) | 3 de 53 tabelas | ⏳ baixando siconv.zip |
| modelo relacional | ✅ | — |
| Portal Transparência | ✅ integrado | — |
| DOU/INLABS | ✅ integrado | — |
| Receita/QSA | ✅ integrado | — |

**Próximo:** carregar o estoque num lake CONSULTÁVEL, separado do banco
operacional (o `tuiu-db` está na raiz de 44 GB com o veredas prod — o lake vai
para `/mnt/dados-gov`).

---

## 9. Inteligência REGIME-AWARE — o dado velho mente se você não datar a regra

Princípio de correção (dono, 19/07): **base legal muda a cada trimestre, e quando
muda, certos "erros" passados ficam DEPRECADOS.** Uma prestação rejeitada em 2014
por "faltou conciliação no modelo X" não ensina nada sobre 2026 se a PC 33/2023
tornou aquele modelo informatizado. Pior: ensina a corrigir um problema que não
existe mais.

O histórico é útil, mas **cada desfecho carrega a regra que o produziu**. A
camada de inteligência TEM que segmentar por regime:

- **desfecho sob regra AINDA vigente** → preditivo (usa para prever/aconselhar);
- **desfecho sob regra DEPRECADA** (PI 424/2016, redações revogadas) → contexto
  (volume, tendência), **nunca prescrição**.

As três peças que já construímos são exatamente o maquinário disto:
1. `regras_normativas` versionada (cada redação com vigência) → mapeia a data do
   instrumento para a regra em vigor naquele dia;
2. o classificador de regime (`_regime`: PI424 / PC33 / PC28 por data+valor);
3. a **vigília normativa** → quando detecta norma nova, marca quais base rates
   ela toca como "fronteira de regime moveu — recomputar / rebaixar o antigo".

**Isso é o moat.** Um concorrente que agrega 18 anos cru produz conselho
confiante-e-errado ("esse erro é comum") sob uma regra que já morreu. Ganhamos
por sermos datados: a resposta certa exige saber *sob qual lei* cada final
aconteceu. Toda tabela de inteligência nasce com coluna de regime.

---

## 10. Além do Transfergov — a fundação de BI

Regra do dono (19/07): **qualquer base marginalmente útil à nossa inteligência de
negócio.** Baixar é barato e reversível; o valor está na análise. Priorizado para
o negócio (operar transferência de OSC executora):

### Tier 1 — universo de cliente e prospecção
- **Mapa das OSC (IPEA)** — o registro definitivo das OSCs brasileiras (cadastro,
  área de atuação, projetos, recursos recebidos). É literalmente o universo do
  nosso cliente. API + bulk. → qualificar/prospectar, enriquecer ficha.
- **Receita — Dados Abertos CNPJ** (~5 GB/mês) — cadastro nacional completo:
  natureza jurídica, CNAE, QSA, Simples, situação, data de abertura. → enriquecer
  QUALQUER cliente/prospect **offline**, achar todas as OSCs por natureza/CNAE,
  rede de sócios — sem depender de BrasilAPI por-CNPJ.

### Tier 1 — o pipeline do dinheiro
- **Emendas parlamentares** (Portal Transparência bulk ✓ + Câmara/Senado API ✓ +
  Siga Brasil/Tesouro) — quem emenda, RP6/7/8/9, execução. Emenda **financia** a
  transferência → conhecer o pipeline = prever volume futuro e saber qual
  parlamentar irriga qual OSC.

### Tier 2 — risco e compliance
- **CEPIM/CEIS/CNEP bulk** (Portal Transparência ✓) — já por API; o bulk dá join
  offline + histórico.
- **TCU** — inidôneos, contas julgadas irregulares, acórdãos (jurisprudência de
  prestação de contas). → risco do prospect, precedente de defesa.
- **CEBAS** — certificação beneficente (saúde/educação/assistência). Relevante
  para os hospitais/santas casas da carteira.

### Tier 3 — contexto
- **IBGE** — municípios, população, PIB (limiares legais).
- **CNES** — estabelecimentos de saúde (os hospitais da carteira).

**Método:** adquirir cedo os baratos de alto valor (Mapa OSC, emendas, sanções
bulk); a Receita (5 GB) é o único compromisso de tamanho — vale pela função de
enriquecimento universal, mas estagia. Tudo mora em
`/mnt/dados-gov/transferegov-lake/` e entra no mesmo lake DuckDB, com a coluna de
regime onde couber.
