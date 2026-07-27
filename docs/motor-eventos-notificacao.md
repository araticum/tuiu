# Motor de eventos + notificação (F1.5)

O "webhook" do andamento — sem credencial de ninguém. Detecta mudança nos
processos do ente por **diff D-1 dos dados abertos** e notback por canais
plugáveis. Substitui, com segurança, a ideia de "ler logado como o usuário"
(que exigiria senha gov.br de terceiros — descartada, ver plano §1/§9).

## Fluxo (na cadeia diária, após o motor de prazos)

```
recorte g2/detru  →  eventos.py (diff vs entidades_estado)  →  eventos
                                                                  │
                                              notificador.py  ────┤→ outbox   (sempre; WhatsApp-ready)
                                                                  ├→ webhook  (POST JSON, se configurado)
                                                                  └→ whatsapp (Cloud API própria, se configurada)
```

- **eventos.py**: compara cada item do recorte com o último estado conhecido
  (`entidades_estado`, sobrevive a dia pulado). Emite `mudanca` (situação
  mudou), `novo` (item apareceu) e `incremento` (novo empenho/OP/relatório).
  Primeira execução por ente = baseline (semeia estado, não dispara em massa).
- **notificador.py**: para cada evento sem entrega, monta a mensagem e despacha.
  Idempotente por (evento, canal, endereço).

## Canais e configuração (env)

| Canal | Quando dispara | Config |
|---|---|---|
| `outbox` | sempre | — (persiste em `entregas`, status `pendente`) |
| `webhook` | se `TUIU_WEBHOOK_URL` **ou** destinatário `canal='webhook'` | `TUIU_WEBHOOK_URL=https://seu-endpoint` |
| `whatsapp` | se destinatário `canal='whatsapp'` **e** Cloud API configurada | `TUIU_WPP_TOKEN`, `TUIU_WPP_PHONE_ID` (Cloud API oficial da Meta) |
| `seriema` | grupo **interno** de operação — não chega ao cliente | `TUIU_SERIEMA_*` |

- `TUIU_WPP_DRYRUN=1` monta o payload e **não** envia (teste). O payload sai
  inteiro no `detalhe` da entrega — é o que se confere antes de virar a chave.
- **Não** usa a Seriema de produção do oasis.v2 (decisão do dono 18/07). E a
  sessão Seriema não serviria para o caso do WhatsApp direto: ela só fala com
  GRUPO (`isGroupJid` recusa qualquer outro JID). Por isso o canal `whatsapp` é
  a **Cloud API oficial** (decisão do dono, 27/07) — `app/wpp_cloud.py`.
- Segredos ficam no cofre DPAPI / `.env` do host — nunca no código.

### Template (obrigatório para alerta proativo)

Aviso de andamento cai **fora da janela de 24h**, e aí a Meta só entrega
mensagem de template aprovado. Cadastrar no WhatsApp Manager como
`tuiu_andamento`, categoria **UTILITY**, idioma **pt_BR**, corpo:

```
*Tuiú* · {{1}}

*{{2}}*
{{3}}
{{4}}

{{5}}

Abrir: {{6}}
_Transferegov · dados de {{7}} · D-1_
```

| | conteúdo | exemplo |
|---|---|---|
| `{{1}}` | tipo do evento | `mudança de andamento` |
| `{{2}}` | cliente | `FUNDACAO FACULDADE DE MEDICINA` |
| `{{3}}` | instrumento | `Convênio/CR 850704` |
| `{{4}}` | transição | `Prestação de Contas em Análise → … em Complementação` |
| `{{5}}` | o que fazer | `Prazo: 14/08/2026 (em 18d) · bola com o convenente · Próximo passo: …` |
| `{{6}}` | ficha do cliente | `https://tuiu.araticum.net/cliente.html?doc=60453032000174` |
| `{{7}}` | data do dado | `25/07/2026` |

Se a Meta recusar `{{6}}` por ser URL inteira, mover a base para o texto fixo do
template (`https://tuiu.araticum.net/cliente.html?doc={{6}}`) e passar só o CNPJ
— aí `TUIU_CONSOLE_URL` e o template têm que combinar, e trocar o domínio passa
a exigir nova aprovação.

⚠️ A Meta recusa parâmetro com quebra de linha, tabulação, 5+ espaços seguidos
ou vazio (erro 132000). O parecer do órgão vem do CSV **com** `\n` e `\t`, então
`wpp_cloud.limpar_parametro` normaliza tudo antes de enviar — a quebra de linha
mora no corpo do template, nunca no valor. Travado em `teste_wpp_cloud.py`.

### A mensagem se basta — e ainda leva o link

Carrega o que decide (instrumento, transição, prazo, de quem é a bola, próximo
passo e a exigência do órgão, puxados de `marcos` por `notificador.contexto()`)
**e** o link da ficha: `{TUIU_CONSOLE_URL}/cliente.html?doc=<cnpj>`, que abre no
celular na tela de login do Tuiú.

É a ficha do cliente, **não a mesa**: a `/mesa.html` não lê query param, então
um link para ela abriria o backlog inteiro da carteira em vez do caso avisado.
Deep-link por item da mesa é trabalho em aberto.

⚠️ A URL sai de `TUIU_CONSOLE_URL` (default `https://tuiu.araticum.net`) e é a
MESMA nos dois caminhos, texto e template — duas fontes divergiriam caladas e o
erro só apareceria no celular de quem recebeu.

### Destinatários

```
python ferramentas/destinatario.py --listar
python ferramentas/destinatario.py --add 61999990000 --canal whatsapp   # '*' = carteira toda
python ferramentas/destinatario.py --testar 5561999990000               # 1 mensagem, fora do motor
```

Cadastrar **não liga** o canal: continuam valendo as duas travas em série
(`notificacoes_ativas` + `canal_whatsapp`), que se ligam em `/notificacoes.html`
com autor e horário registrados.

### Idempotência

A entrega é **reservada e comitada antes do envio**. A Cloud API não tem dedup
por chave (a sessão Seriema tinha), então sem a reserva uma queda no meio do
laço faria o mesmo alerta tocar o telefone de alguém de novo no dia seguinte. O
preço: entrega em `erro` não é retentada sozinha — reenvio é ato deliberado.

## API / tela

- `GET /api/eventos?cnpj=&limite=` · `GET /api/entregas?canal=`
- Tela `/eventos.html`: feed de mudanças + outbox WhatsApp-ready.

## Inbox parser (F1.6) — o recado privado do portal

O diff D-1 vê o andamento público; o **inbox parser** cobre o que só chega por
e-mail (diligência, complementação solicitada, resultado de análise). O
convenente cria um filtro que **reencaminha** as notificações do Transferegov
para uma caixa que lemos por IMAP — sem nenhuma credencial gov.br.

**Segurança (e-mail = conteúdo não-confiável):**
- só remetente na allowlist `TUIU_INBOX_REMETENTES` vira evento; o resto fica
  `suspeito` e **nunca** notifica (testado com fixture de phishing/injeção);
- o parser só **extrai e classifica** — nunca executa, nunca segue link
  (links são removidos e contados);
- e-mail sem CNPJ de ente monitorado → `nao_atribuido` (aparece, mas não dispara).

Atribuição: CNPJ no corpo → ente monitorado; senão mapa `inbox_origem`
(endereço reencaminhador → CNPJ); senão `nao_atribuido`. Eventos de inbox usam
a MESMA tabela `eventos` (origem='inbox') → mesmo notificador.

Config IMAP: `TUIU_IMAP_HOST`, `TUIU_IMAP_USER`, `TUIU_IMAP_PASS`,
`TUIU_IMAP_FOLDER` (default INBOX). Sem eles, a cadeia diária pula o passo.

⚠️ CALIBRAR: os domínios remetentes e as frases de classificação em
`parser_email.py` são um ponto de partida — ajustar contra e-mails REAIS do
Transferegov (marcados `CALIBRAR` no código).

## Rodar

```
py -3 backend/app/eventos.py                          # diff (migra sozinho)
py -3 ingest/inbox/coletar_inbox.py --eml <pasta>     # inbox por .eml (teste)
py -3 ingest/inbox/coletar_inbox.py                   # inbox por IMAP (env)
py -3 backend/app/notificador.py                      # despacha
py -3 ops/rodar_diario.py                             # cadeia inteira
py -3 -m pytest testes/teste_wpp_cloud.py             # formato do template + autossuficiência
py -3 testes/smoke_eventos.py                         # smoke diff (webhook + wpp dryrun)
py -3 testes/smoke_inbox.py                           # smoke inbox (allowlist + atribuição)
```

## Quando o dado chega (e por que a cadeia é 09h30)

`ops/sonda_atualizacao.py` mede, em vez de estimar. Dois sinais:

- **detru (CSV)** — `Last-Modified` do HEAD dos ZIPs é a hora exata da
  publicação, sem baixar os 300 MB. Medido em 27/07: **08:13 BRT**. É a fonte
  que hoje produz quase todo evento (`convenio_legado`).
- **g2 (API)** — `data_ultima_atualizacao` vem carimbado `T00:00:00`: diz de que
  DIA é o dado, nunca a hora da carga. A hora sai do *flip* entre sondagens.

Evidência indireta acumulada: em 19→27/07, às 09h36 o campo já mostrava o dia
corrente e as 100 conferências de `verificar.py` batiam — a carga termina antes
disso. A cadeia às 09h30 tem ~1h15 de folga sobre o detru.

```
py -3 ops/sonda_atualizacao.py            # uma sondagem (o timer chama assim)
py -3 ops/sonda_atualizacao.py --resumo   # janelas medidas até agora
```
