# Plano — Tuiú: SaaS de gestão de transferências da União (Transferegov.br)

> Versão 1.0 · 2026-07-17 · **aprovado pelo dono em 17/07/2026** — codinome **Tuiú** (tuiuiú, o jaburu do Pantanal).
> Repo do produto: `araticum/tuiu` (decisão do dono, 17/07/2026); peças do `araticum/oasis.v2` entram como doadoras.
> Pesquisa verificada em fontes oficiais em 17/07/2026 (gov.br/transferegov, Planalto/Câmara, STN, TCU, APIs testadas ao vivo).
> Nada implementado ainda — implementação começa pela F0.

## 1. Tese do produto

**Cockpit do lado de quem RECEBE**: prefeituras, consórcios e OSCs operando convênios, contratos de repasse,
termos MROSC e emendas Pix no Transferegov.br. O governo tem plataforma, painel e IA de fiscalização
("Malha Fina" da CGU pontua risco de cada prestação de contas); o convenente tem tela crua, prazo perdido e
multa. O Tuiú é o espelho gerencial + motor de prazos + compliance preventivo, alimentado pelas APIs e
CSVs públicos oficiais (diários), com alerta por WhatsApp e documento assinado A1 na saída.

Por que agora (números verificados):

| Fato | Número | Fonte |
|---|---|---|
| Municípios com pendência no CAUC (não podem celebrar) | ~80% dos 5.569 | estudo CNM |
| Municípios atrasados no Relatório de Gestão de emendas Pix | 82% (4.590 entes, jun/2026) | CNM / Transferegov |
| Multa por não enviar plano/relatório de emenda Pix | **1% ao dia** sobre o valor | IN TCU 93/2024 + AGU |
| Obras com recurso federal paralisadas | 11.944 (52%), R$ 15,9 bi já gastos | Painel TCU |
| Emendas parlamentares no orçamento 2026 | ~R$ 61 bi (RP6 R$ 26,6 bi) | Senado |
| LDO 2026: piso de pagamento de emendas impositivas | 65% até 30/06/2026 | Lei 15.321/2025 |
| Transferido acumulado pela plataforma desde 2023 | > R$ 500 bi | MGI |
| Equipe típica de convênios em município pequeno | 1–3 pessoas | posicionamento dos concorrentes |

**O que o produto NÃO é** (fronteira dura): não transaciona no Transferegov (não existe API pública de
escrita para convenente — proposta, OBTV/OPP e prestação de contas são protocolados pelo usuário na
plataforma oficial); não é ERP contábil (Betha/Elotech ficam com a contabilidade/TCE estadual); não opera
pagamento. O Tuiú **prepara, vigia, documenta e denuncia prazo** — o clique final é do usuário, com o
material pronto.

## 2. O terreno — a plataforma (estado jul/2026)

Transferegov.br = sucessor do SICONV (2008) e da Plataforma +Brasil (2019), renomeado pelo Decreto
11.271/2022, sistema estruturante do **Sigpar** (órgão central SEGES/MGI). Uso obrigatório para
transferências do Orçamento Fiscal e da Seguridade Social.

| Módulo | Cobre | Relevância p/ Tuiú |
|---|---|---|
| **Discricionárias e Legais** | Convênios, contratos de repasse (mandatária Caixa), termos de fomento/colaboração/parceria (MROSC) — ciclo completo herdeiro do SICONV | núcleo do produto |
| **Transferências Especiais** | Emendas Pix (art. 166-A CF): plano de ação, execução, relatório de gestão | núcleo (é onde a dor sangra) |
| **Fundo a Fundo** | PNAB/Aldir Blanc, Paulo Gustavo, Conectividade etc. | fase 2+ |
| **TED** | Órgão federal → órgão federal | fora de escopo (sem cliente nosso) |
| **Cadastro 2.0** | Credenciamento de entes, dirigentes, cadastradores | onboarding do cliente |
| **Obrasgov (CIPI)** | Obras vinculadas, medições, georreferência | fase obras |
| **Gestão de Passivos** | Estoque pré-SICONV (~45 mil contas / R$ 28 bi) | fora de escopo |
| Apps oficiais | Cidadãogov, Fiscalgov (vistoria georref.), Gestorgov | benchmark de UX |

**Ciclo de vida que o produto modela** (Discricionárias e Legais): credenciamento → divulgação de
programas/chamamento → proposta + plano de trabalho (cronogramas físico e de desembolso) → análise e
celebração (empenho, assinatura, publicação; obras entram no CIPI) → execução (licitação registrada — com
integração a sistemas de compras —, conta bancária específica, pagamentos OBTV→**OPP**, rendimentos,
ajustes de PT, aditivos, prorroga de ofício) → acompanhamento (vistorias, fotos georreferenciadas) →
**prestação de contas contínua** (começa na 1ª parcela; Registro → Envio → Análise; resultado Aprovada /
com Ressalvas / Rejeitada; análise informatizada com nota de risco — Portaria Conjunta MGI/CGU 41/2023 +
Malha Fina CGU) → TCE via e-TCE se der ruim.

Mudanças em curso que afetam o desenho: **OPP** (Ordem de Pagamento da Parceria, sucessora da OBTV,
pagamento via API bancária BB/Caixa/BNB com PIX — em desenvolvimento); **MultiEntes** (jul/2026→mar/2028:
estados e municípios passam a operar transferências PRÓPRIAS na plataforma — pilotos RN, AC, BA, RR) —
o mercado endereçável cresce; **Cadastro 2.0** novo; defeso eleitoral vigente (ver §3).

## 3. Marco legal → motor de regras

O achado central da pesquisa: **três regimes normativos coexistem** e o sistema precisa saber em qual
regime cada instrumento vive — mais o regime próprio das emendas Pix. Errar o regime = errar todo prazo.

| Regime | Quem rege | Aplica-se a |
|---|---|---|
| **Legado** | Decreto 6.170/2007 (revogado 01/09/2023) + PI 424/2016 em ultratividade | instrumentos celebrados até 31/08/2023 (migráveis por aditivo); prestação de contas 60 dias, guarda 10 anos |
| **Completo** | Decreto 11.531/2023 + PC MGI/MF/CGU 33/2023 (alterada por PC 29/2024, 84/2025, 99/2025, 45/2026) | instrumentos **acima** do teto do art. 184-A (R$ 1.576.882,20 em 2025/26) |
| **Simplificado** | Lei 14.133 art. 184-A (Lei 14.770/2023) + PC 28/2024 (alterada por PC 15/2025, 102/2025, 46/2026) | instrumentos ≤ teto; sem análise prévia de TR/licitação; **parcela única obrigatória**; verificação final por visita de constatação; retroativo a celebrados desde 01/04/2021 via aditivo |
| **Especiais (Pix)** | CF 166-A + LC 210/2024 + IN TCU 93/2024 + ADPF 854 (STF) + PCs 115/2024, 2/2025, 15/2025, 2/2026 | plano de trabalho prévio, conta específica em banco oficial, ≥70% capital, veda pessoal/dívida, relatório de gestão, retenção de 1% |
| **MROSC** | Lei 13.019/2014 + Decreto 8.726/2016 reformado pelo Decreto 11.948/2024 | OSCs: aditivo até +50%, remanejamento ≤10% sem anuência |

**Tabela paramétrica** (vira tabela `regras_normativas` versionada — valores mudam por decreto/portaria
quase todo ano; cada linha carrega base legal + vigência):

| Parâmetro | Valor hoje | Base |
|---|---|---|
| Corte simplificado × completo | R$ 1.576.882,20 (atualização anual) | 14.133 art. 184-A + Decreto 12.343/2024 |
| Níveis do regime completo (obras) | >teto–5 mi / 5–20 / 20–80 / >80 mi (I–IV); V = demais | PC 33 art. 7º |
| Vigência máxima por nível | 36/48/60/72 meses (flexibilizada pela PC 99/2025) | PC 33 art. 35, VII |
| Cláusula suspensiva | 9m prorrogável a 18m; transitório: 36m (celebr. 2024/25) e até **30/09/2026** p/ celebrados ≤31/12/2023 | PC 33 art. 24; PC 99/2025 |
| Parcelas | mín. 3 (níveis I–IV); simplificado: única; adiantamento 5% p/ projetos | PC 33 art. 68 §6º; PC 102/2025 |
| Prorroga de ofício | obrigatória, = exato atraso de liberação | PC 33 art. 35, XXIV |
| Inexecução tolerada | 365 dias (retomada em 6 meses) | PC 33 (alteração 2025) |
| Guarda documental | 5 anos pós-aprovação (novo) / 10 anos (legado) | PC 33 art. 9º §2º; PI 424 |
| Vigência × mandato | vedado terminar no último trimestre do mandato ou 1º do seguinte | PC 33 art. 13, V |
| Despesa administrativa (entidade privada) | ≤15% | PC 33 art. 22 §1º |
| **Defeso eleitoral** | 3 meses pré-pleito — **vigente desde 04/07/2026** (eleições 04/10); exceção: obra em andamento c/ cronograma, calamidade | Lei 9.504/97 art. 73, VI, "a" |
| Emendas Pix: fluxo do plano | complementação 30d, parecer 60d, reenvio 30d | PC MGI/MF 2/2025 art. 3º |
| Emendas Pix: multa | 1%/dia sem plano/relatório (estoque 2020–2024) | IN TCU 93/2024 |
| LDO 2026: piso de pagamento | 65% de RP6+RP7 até 30/06/2026 | Lei 15.321/2025 |
| CAUC | 26 itens (7 novos: precatórios, SIAFIC, transparência, Fundeb) | IN STN/MF 8/2025 (vigor 17/02/2025) |
| PNCP p/ municípios ≤20 mil hab. | prazo de adaptação expira 01/04/2027 | 14.133 art. 176 |
| RP6 / RP7 | 2% RCL (metade saúde) / 1% RCL | ECs 86/100/126 |

⚠ A confirmar no texto integral antes de cravar default: prazo supletivo de apresentação da prestação de
contas na PC 33/2023 (é cláusula obrigatória do instrumento — art. 35, XXX; o valor default por regime
precisa de leitura do DOU) e números exatos das PCs "45/2026"/"46/2026".

**"Legais" no escopo**: transferências automáticas (PNAE, PNATE, PDDE — sistemas do FNDE) e fundo a fundo
(SUS/SUAS) rodam majoritariamente FORA do fluxo de convênios; o módulo oficial as agrega no painel. O
Tuiú trata como **carteira informativa** (mostrar recebimentos e prazos de prestação aos sistemas
próprios), não como fluxo gerido — classificação configurável.

## 4. Dados e integrações (tudo testado ao vivo em 17/07/2026)

| Fonte | O que dá | Tech/limites | Status |
|---|---|---|---|
| **API g2** `api-publica.transferegov.gestao.gov.br` | `/parcerias` (16 rotas: programa, proposta, parceria, conta, análise, cronograma-desembolso, empenho, **extrato-bancario**, ordem-pagamento, metas, itens, emendas do beneficiário, `data-atualizacao`) e `/especiais` (21 rotas: planos de ação/trabalho + histórico, empenhos, OB/OP, **lançamentos e saldo de conta**, relatórios de gestão) | OpenAPI 3, sem chave, só GET, 200 linhas/página, envelope `total_items`, carga diária (~09h, checar `/data-atualizacao`) | ✅ é a fonte primária |
| **API g1** `api.transferegov.gestao.gov.br` | especiais/TED/fundoafundo (PostgREST 11, cap 1000/página) | **desliga 31/08/2026** | usar só o que faltar na g2 |
| **CSVs diários** `repositorio.dados.gov.br/seges/detru/` (espelho: `api-publica…/downloads/dadosgov/`) | estoque COMPLETO de discricionárias desde 2008: proposta, convênio, emenda, empenho, desembolso, pagamento, OBTV, licitação, contrato, cronogramas, aditivos, prorrogas, histórico de situação, CIPI, coordenadas de obra (~75 arquivos; `siconv.zip` 3 GB; modelo ER incluso) | extração diária até 09h | ✅ fonte do estoque/histórico |
| Roadmap oficial da API g2 | Atos Preparatórios jul–out/2026 · Instrumentos nov/2026–fev/2027 · Execução Financeira mar–jun/2027 · Obras jul–out/2027 | — | o CSV cobre o buraco até lá |
| **Portal da Transparência** | `/api-de-dados/convenios` e `/emendas` + documentos | chave grátis; 90 req/min | ✅ enriquecimento |
| **Compras.gov dados abertos** | `modulo-pesquisa-preco` (JSON/CSV), contratações 14.133, UASGs | aberto | pesquisa de preço p/ plano de trabalho |
| **PNCP** | editais/contratos do convenente | aberto (consulta) | cruzamento licitação↔convênio |
| **SICONFI/ORDS** | RREO/RGF/DCA do ente | aberto, 5000/página | prever CAUC (itens fiscais) |
| **Obrasgov API** | projeto-investimento, execução física, georref | aberto | fase obras |
| **SIOP** | emendas: dotação→pagamento por autor (SPARQL público) | SPARQL aberto; API Conecta restrita | radar de emendas |
| **CAUC** `sti.tesouro.gov.br` | extrato de 26 itens por CNPJ | **sem API** — consulta por tela | scraping via doc-extractor (fail-safe) |
| Câmara/Senado dados abertos | autores de emendas | aberto | crosswalk parlamentar |

**Escrita** (transação): só para sistemas credenciados por ofício à DTPAR/SEGES-MGI + token Bearer —
verticais **compras** (`maisbrasil-api`: POST processo-compra) e **obras** (planilha orçamentária +
boletim de medição; players pequenos já integrados: EngeGOV, LCL Plan, GESPAM). API de Cadastro "em
breve" desde 2023. SOAP do SICONV: extinto. **Não existe escrita para convenente** — fronteira do §1
confirmada; o credenciamento nas verticais compras/obras fica como opção F6 se cliente demandar.

**Estratégia de ingest**: recorte por ente monitorado (CNPJ/IBGE do tenant) + tabelas de referência
(programas, emendas, órgãos) — NÃO o lake nacional. Cadeia diária no padrão xyops do Veredas (serial,
job-limit=1, pós-carga ~09h30): `g2_parcerias_pull → g2_especiais_pull → csv_detru_delta → cauc_check →
marcos_recalc → alertas`. Lake nacional completo (3 GB/dia) é opcional futuro no Carcará para
inteligência de mercado, não requisito do produto.

## 5. Mercado e posicionamento

**Concorrência** (verificada): ERPs municipais (Betha, Elotech, IPM, GOVBR) param na
contabilidade/prestação ao TCE — nenhum tem módulo público do ciclo Transferegov. Diretos: **Gestor de
Convênios** (captação por CNPJ, monitor CAUC/certidões, IA de plano de trabalho) e **+Convênios/QIATech**
(unifica 5 sistemas, IA de proposta, obras com medição/fotos, alertas WhatsApp) — ambos pequenos, preço
não público. **CNM/Plataforma Êxitos** é grátis p/ filiados mas cobre só a DESCOBERTA de oportunidades.
Prosas atende o lado do órgão/OSC em editais. CRMs de mandato (Conecta Gabinete etc.) veem a emenda do
lado do parlamentar. **Ninguém entrega**: motor de prazos com base legal citada, CAUC diário com diff,
relatório de gestão de Pix guiado, documento final assinado ICP-Brasil, preço público.

**Segmentos e ordem de ataque**: (1) prefeituras pequenas/médias e consórcios (723 ativos — 1 contrato →
N municípios); (2) OSCs com parceria federal (MROSC); (3) assessorias/consultorias de captação
(white-label multi-ente — elas gerem dezenas de municípios); (4) mandatos (radar de emendas — cross-sell
depois). Sinergia interna: municípios monitorados geram licitações → radar comercial para o Veredas; o
plano MPDFT (SaaS GRC como módulo Oasis) valida o padrão "módulo → SaaS".

**Modelo comercial**: assinatura anual **abaixo do teto de dispensa por valor** (art. 75, II, 14.133 —
≈R$ 65 mil em 2026; confirmar valor exato do decreto anual) = venda direta sem licitação. Preço-âncora
proposto: município R$ 990–2.490/mês por faixa populacional (R$ 12–30 mil/ano — folga sob o teto);
consórcio/assessoria por ente adicional decrescente; OSC R$ 390–690/mês. Pilotos design-partner: 90 dias
grátis, 3 entes. Diferencial de confiança: preço público no site (ninguém no nicho tem) + LGPD by design
(Pedro/DPO — ativo jurídico da casa).

## 6. O produto — superfícies

Personas: **secretário/gestor de convênios** (opera), **prefeito/dirigente** (lê o painel e o PDF),
**contador/controle interno** (regularidade), **assessoria** (multi-ente).

| Superfície | Entrega | Dor que mata |
|---|---|---|
| **Radar** | programas abertos + emendas destinadas ao ente (por CNPJ/IBGE), com filtro e aviso de janela; defeso eleitoral sinalizado | "não sabia que tinha recurso p/ mim" |
| **Carteira** | todos os instrumentos do ente (todas as fontes/tipos) com situação, regime normativo, vigência, financeiro (empenho→OB→pagamento→saldo de conta), timeline de eventos | visão zero → visão única |
| **Prazos** | agenda consolidada derivada do motor de regras (§3): fim de vigência, prestação de contas, suspensiva, relatório de gestão Pix, aditivos, defeso; alerta WhatsApp T-30/T-7/T-1 com base legal citada | multa de 1%/dia, instrumento caduco |
| **Regularidade** | CAUC 26 itens diário + certidões com validade, semáforo, diff-alert ("item X virou pendente ontem"), histórico p/ auditoria | 80% travados sem saber o porquê |
| **Contas & Pix** | checklist de prestação de contas por regime; wizard do Relatório de Gestão de emenda Pix (produz o conteúdo pronto p/ protocolar); pré-análise de risco espelhando a lógica pública da malha fina (Portaria 41/2023) | 82% atrasados; rejeição evitável |
| **Documentos** | dossiê por instrumento (Sargaço), geração timbrada (ofícios, planos, relatório executivo do prefeito) via editor/pdf-render, **assinatura A1 ICP-Brasil** com TOTP | papelada dispersa; "cadê o comprovante de 5/10 anos atrás" |
| **IA** (opt-in, freio de custo) | leitura de programa/chamamento → resumo executivo; rascunho de plano de trabalho com validações objetivas (quantitativo/especificação/local — exigência do regime simplificado); Q&A sobre a norma aplicável ao instrumento | equipe de 1–3 pessoas sem procurador |

## 7. Arquitetura

**Repo próprio `araticum/tuiu`** (decisão do dono, 17/07/2026). Backend no padrão de módulo da casa
(models/router/schemas/services + migrations Alembic + registro no `main.py`), frontend próprio no padrão
do `apps/web` (Next.js 15 App Router). As peças do `oasis.v2` entram como **doadoras** — código
extraído/copiado ou serviço compartilhado; a fronteira exata (o que vira lib comum × o que consome o
serviço vivo do stack veredas) se define na F0.

**Modelo de dados (núcleo)**: `entes_monitorados` (CNPJ/IBGE, esfera, vínculo ao tenant) ·
`instrumentos` (tipo, regime_normativo, nº, concedente/mandatária, situação, vigência, valores, fonte de
dado) · `emendas` (autor, RP, valores, plano de ação) · `marcos` (motor de prazos: tipo, data-limite,
base_legal, status, alertas emitidos) · `movimentos` (espelho financeiro) · `regularidade_itens` (CAUC +
certidões, com histórico) · `regras_normativas` (parâmetro, valor, vigência, base legal — versionada) ·
`ingest_jobs` (padrão `tender_pipeline_jobs`).

**Reuso de peças existentes** (é isso que torna o plano barato):

| Peça | Uso no Tuiú |
|---|---|
| Pipeline ingest Veredas + cadeia xyops | cargas diárias g2/CSV, mesma disciplina serial do PNCP |
| Sargaço | dossiê documental por instrumento (guarda 5/10 anos) |
| candeia-a1 + step-up TOTP | assinatura ICP-Brasil de ofícios/planos/relatórios |
| Seriema (WhatsApp/Telegram/voz) | alertas de prazo e diff de CAUC |
| Buriti + pdf-render | relatório executivo timbrado, plano de trabalho, ofícios |
| Compêndio IA (DeepSeek + freio de custo) | leitura de programas, rascunho de plano, Q&A normativo |
| doc-extractor (Playwright, fail-safe, host BR) | CAUC via `sti.tesouro.gov.br` + certidões |
| Framework de renovação da Habilitação | monitor de certidões do ente (TCU/Falimentar já ao vivo) |
| Tamanduá (multi-tenant + SMTP) | tenancy na F5 |
| Ariranha | billing do SaaS |
| Carcará | opcional: lake nacional p/ inteligência de mercado |

**Tenancy e deploy**: F0–F4 rodam single-tenant no araticum, dogfood com entes reais escolhidos pelo
dono. F5 sobe stack `tuiu` próprio (compose próprio, DB próprio) com isolamento por tenant — não
misturar dados de cliente com o uso interno da Araticum. **LGPD**: gate `D:\Quimera\PRIVACY.md` desde a
concepção (regra permanente): dados-fonte são públicos oficiais, mas dados bancários de executores
(expostos na API pública) entram minimizados/mascarados; usuários do tenant = mínimo necessário; DPA no
contrato.

## 8. Roadmap (walking skeleton — cada fase é vendável)

| Fase | Entrega | Pronto quando |
|---|---|---|
| **F0 — Radar do ente** | ingest g2 (`/parcerias` + `/especiais`) + delta CSV por CNPJ/IBGE; tela Carteira com situação/vigência/financeiro e `data_atualizacao` | para 3 entes reais, a carteira bate com o painel público oficial |
| **F1 — Motor de prazos** | `regras_normativas` + `marcos` (§3 completo, incl. defeso e Pix); agenda; alertas WhatsApp T-30/7/1 | alerta real disparado de prazo real, com base legal no texto |
| **F2 — Regularidade** | CAUC diário (doc-extractor) + certidões (reuso Habilitação); semáforo, diff-alert, histórico | item que vira pendente gera WhatsApp em ≤24h, com evidência guardada |
| **F3 — Cockpit & contas** | dossiê Sargaço, checklist por regime, wizard do Relatório de Gestão Pix, relatório executivo PDF timbrado assinado A1 | um instrumento real gerido ponta a ponta; relatório assinado entregue |
| **F4 — IA** | resumo de programa, rascunho de plano de trabalho validado (quantitativo/espec./local), Q&A normativo — atrás do freio de custo | rascunho de plano de programa real aprovado pelo dono |
| **F5 — SaaS** | multi-tenant (tamanduá), onboarding, billing Ariranha, preço público, DPA/LGPD formal, stack `tuiu` no araticum | 2 tenants pagantes isolados em produção |
| **F6 — opcionais** | credenciamento compras/obras (ofício DTPAR) se cliente exigir; vigília normativa automatizada (DOU/comunicados); módulo obras (CIPI/medições); radar p/ mandatos | por demanda |

Operação contínua desde F1: **vigília normativa** — as portarias conjuntas mudam a cada trimestre (4
alterações na PC 33 desde 2023; ciclo anual de comunicados de emendas); monitorar
`gov.br/transferegov/legislacao` + comunicados e atualizar `regras_normativas` com vigência, nunca
sobrescrever.

## 9. Riscos e gotchas

| Risco | Mitigação |
|---|---|
| Norma em mutação constante (PCs trimestrais, valores anuais por decreto) | tabela paramétrica versionada + vigília normativa; nunca hardcode |
| API g1 desliga **31/08/2026** | construir direto na g2 + CSVs; zero dependência da g1 |
| Cobertura da g2 ainda parcial (execução financeira plena só em 2027) | CSV detru diário cobre o buraco (testado: estoque completo) |
| CAUC sem API (scraping) | doc-extractor fail-safe + evidência (print/HTML) guardada; degradar sem quebrar |
| CNM grátis na descoberta | competir na EXECUÇÃO/compliance, não na descoberta; radar é isca, não o produto |
| ERPs incumbentes acordarem | velocidade + nicho + preço público + WhatsApp/A1 (integrações que eles não têm) |
| Dado é D-1 (carga ~09h), não real-time | `data_atualizacao` sempre visível; comunicação honesta |
| Dados bancários de executores na API pública | minimizar/mascarar; gate PRIVACY.md |
| Prazo default de prestação de contas (PC 33) não confirmado | ler texto integral no DOU antes da F1; até lá, prazo vem da cláusula do instrumento (campo editável) |
| Equipe = 1 dev | fases enxutas, reuso máximo (§7), cada fase vendável sozinha |
| MultiEntes muda o jogo até 2028 | é oportunidade (mais entes na plataforma); acompanhar pilotos RN/AC/BA/RR |

## 10. Decisões

**Travadas (dono, 17/07/2026):**
- Codinome: **Tuiú**.
- Repo próprio **`araticum/tuiu`** (plano versionado aqui; peças do oasis.v2 como doadoras).

**A travar:**
1. Quais 3 entes reais para dogfood na F0 (sugestão: municípios-alvo comerciais da Araticum).
2. Ordem de segmento: prefeituras+consórcios primeiro (recomendado) vs OSCs vs assessorias.
3. Lake: recorte por tenant no araticum (recomendado) vs lake nacional no Carcará desde já.
4. Pricing final e se o preço vai público no site (recomendado: sim).
5. Marca do produto (nome de fachada ≠ codinome) e domínio.
6. F6 compras/obras: pedir credenciamento à DTPAR cedo (fila burocrática) ou só sob demanda.

## 11. Fontes principais (verificadas 17/07/2026)

- Portal e manuais: <https://www.gov.br/transferegov/pt-br> · manuais Discricionárias: <https://www.gov.br/transferegov/pt-br/manuais/transferegov/discricionarias> · capacitação/ENAP: <https://www.gov.br/transferegov/pt-br/capacitacao>
- Legislação: Decreto 11.531/2023 · PC 33/2023 (consolidada): <https://www.gov.br/transferegov/pt-br/legislacao/portarias/portaria-conjunta-mgi-mf-cgu-no-33-de-30-de-agosto-de-2023> · PC 28/2024 (simplificado) · LC 210/2024 · IN TCU 93/2024 · IN STN/MF 8/2025 (CAUC) · LDO 2026 (Lei 15.321/2025)
- APIs: g2 <https://api-publica.transferegov.gestao.gov.br/> (`/parcerias`, `/especiais`, `/downloads`) · g1 docs <https://docs.api.transferegov.gestao.gov.br/> · CSVs <http://repositorio.dados.gov.br/seges/detru/> · dados abertos (hub): <https://www.gov.br/transferegov/pt-br/ferramentas-gestao/dados-abertos> · integração compras/obras: <https://www.gov.br/transferegov/pt-br/sobre/apis-integracao> · Portal da Transparência: <https://api.portaldatransparencia.gov.br/swagger-ui/index.html> · CAUC: <https://sti.tesouro.gov.br/ng/>
- Painéis: <https://transferegov.paineis.gov.br/> · <https://parceriasgov.paineis.gov.br/> · Qlik Discricionárias: <https://dd-publico.serpro.gov.br/extensions/painel/DiscricionariasInicio.html>
- Mercado: CNM <https://cnm.org.br/municipios/transferencias> · Painel obras TCU <https://sites.tcu.gov.br/listadealtorisco/gestao_das_obras_paralisadas.html> · concorrentes: <https://gestordeconvenios.com.br/> · <https://www.qiatech.com.br/>
