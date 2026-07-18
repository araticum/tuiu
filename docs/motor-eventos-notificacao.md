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
| `whatsapp` | se destinatário `canal='whatsapp'` **e** provider configurado | `TUIU_WPP_TOKEN`, `TUIU_WPP_PHONE_ID` (WhatsApp Cloud API própria) |

- `TUIU_WPP_DRYRUN=1` monta o payload e **não** envia (teste).
- **Não** usa a Seriema de produção do oasis.v2 (decisão do dono 18/07):
  instância de notificação própria entra na **F5**; até lá, `webhook` já leva o
  evento para onde o dono quiser (inclusive uma ponte WhatsApp própria).
- Segredos ficam no cofre DPAPI / `.env` do repo — nunca no código.

### Destinatários

`INSERT INTO destinatarios (cnpj, canal, endereco) VALUES ('*','whatsapp','5561999990000');`
(`cnpj='*'` = todos os entes; ou o CNPJ específico). WhatsApp Cloud API fora da
janela de 24h exige *template* aprovado — para alertas proativos, cadastrar um
template e trocar o corpo `text` por `template` no `notificador._enviar_whatsapp`.

## API / tela

- `GET /api/eventos?cnpj=&limite=` · `GET /api/entregas?canal=`
- Tela `/eventos.html`: feed de mudanças + outbox WhatsApp-ready.

## Rodar

```
py -3 backend/app/eventos.py       # detecta (migra sozinho)
py -3 backend/app/notificador.py   # despacha
py -3 ops/rodar_diario.py          # cadeia inteira (inclui os dois)
py -3 testes/smoke_eventos.py      # smoke ponta a ponta (webhook sink + wpp dryrun)
```
