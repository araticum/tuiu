# Sessão do operador — o contorno do "só CPF opera"

## O problema

O Transferegov **só aceita CPF como operador**. Mesmo com contrato
**empresa → Araticum**, quem faz as prestações é **uma pessoa física** logada
com o gov.br dela. Não existe cadastro de "empresa operando para empresa", nem
API transacional para convenente (verificado: só há APIs de escrita para
sistemas de compras/obras de entes, mediante ofício).

Consequências que o produto tem de respeitar:

1. Nada do que é privado do portal chega por API — só pela **tela logada**.
2. As notificações por e-mail vão para **a caixa do operador PF**, não da empresa.
3. Todo ato (enviar proposta, protocolar prestação, responder diligência)
   continua sendo **feito por uma pessoa**, com responsabilidade pessoal.

## O que fazemos — e o que NÃO fazemos

| | |
|---|---|
| ✅ **Attach** numa janela que o operador **já autenticou** | ❌ Automatizar login (usuário/senha/2FA) |
| ✅ Ler páginas (GET) e extrair texto/estrutura | ❌ Clicar, preencher, enviar, protocolar |
| ✅ Registrar o que leu em trilha de auditoria | ❌ Guardar credencial de quem quer que seja |
| ✅ Virar evento/alerta no Tuiú | ❌ Agir em nome do operador |

O módulo `ingest/portal/sessao_operador.py` **não tem** função de clique nem de
preenchimento — a restrição é estrutural, não só de disciplina. Se a sessão não
estiver autenticada, ele avisa e para.

## Como usar

1. Abrir a janela do operador (uma vez por dia de trabalho):

   ```
   chrome.exe --remote-debugging-port=9222 --user-data-dir="D:\tuiu\.perfil-operador"
   ```

2. **Nessa janela**, acessar o Transferegov e **fazer login gov.br manualmente**
   (inclusive o 2FA). O Tuiú não participa dessa etapa.

3. Rodar o leitor:

   ```
   set TUIU_SESSAO_ATIVA=1
   py -3 ingest/portal/sessao_operador.py --descobrir   # 1ª vez: salva estrutura p/ calibrar
   py -3 ingest/portal/sessao_operador.py               # leituras do dia
   ```

Saída em `data/sessao/<data>/` (texto, HTML e estrutura na descoberta) +
`auditoria.jsonl` com cada navegação. Nada disso é versionado.

## ⛔ Resultado do teste com A1: login automatizado está FORA (18/07/2026)

Testamos no araticum, com o A1 real da Araticum, para validar a premissa de
"container loga sozinho e sustenta a sessão". O caminho foi percorrido até o
fim e o veredito é **negativo — por decisão da plataforma, não por limitação
técnica nossa**:

1. O Transferegov tem **um único caminho de login**: "Entrar com gov.br" →
   `sso.acesso.gov.br` (não há login local no IdP).
2. Na tela do gov.br, "Seu certificado digital" **não é link navegável** — é
   `<button id="login-certificate">` com handler JS. Não há URL para um GET.
3. Ao acionar esse botão, o gov.br dispara **hCaptcha**
   (`api.hcaptcha.com/getcaptcha/...`) — o login é **deliberadamente protegido
   por anti-bot**.

**Não resolvemos nem contornamos captcha.** É linha que não se cruza, e é o
recado explícito da plataforma de que login automatizado não é bem-vindo.
Portanto: **o container não se autentica sozinho.**

Achados laterais do teste (úteis e registrados):
- O A1 da Araticum é **e-CNPJ** (OIDs `2.16.76.1.3.3/.7`), válido até
  17/09/2026 — e a operação no Transferegov exige **e-CPF** de qualquer forma.
- `client_certificates` do Playwright carrega o `.p12` sem tocar no store do SO
  (mecanismo funciona; o bloqueio é o captcha, não o certificado).
- Segredo montado precisa pertencer ao **uid do container** (`10001`), com
  `chmod 400` — `600 pedro` não é legível pelo processo não-root.

### O que fica valendo

O **modelo attach**: o operador faz o login **manualmente** (resolvendo o
captcha, como humano) uma vez, e o container **sustenta e lê** aquela sessão.
Isso preserva tudo o que importa — estado do mesmo dia, sem D-1 — sem
automatizar autenticação nem burlar proteção. A pergunta que sobra ("por
quantos dias a sessão se sustenta com keepalive?") continua respondível: é só
medir a partir de um login manual.

## Modo container com A1 (leitura no mesmo dia, sem depender do D-1)

**Fronteira travada com o dono (18/07): o certificado serve só para LOGIN.
Nada é assinado com ele.** O objetivo é puxar no mesmo dia a mudança de estado
dos representados — nenhuma ação é tomada.

### A fortaleza em volta do A1

| Camada | O que faz valer |
|---|---|
| `auth_certificado.py` | única peça que vê o certificado; entrega um contexto autenticado e **não importa nenhuma API de assinatura** |
| `sessao_loop.py` / `sessao_operador.py` | leem; **não existe** clique, preenchimento, envio ou upload no código (verificável por grep) |
| `Dockerfile` | usuário não-root; **não copia** o certificado para a imagem; não instala nada de assinatura |
| `compose.yaml` | `.pfx` montado **`:ro`**; PIN via **docker secret** (arquivo), não em env de imagem; `read_only: true`; `cap_drop: ALL`; `no-new-privileges`; **sem portas publicadas** |
| cofre | PIN em `TUIU_A1_SENHA` (DPAPI) ou arquivo montado em runtime — nunca em código |

### Cadência (sessão longa > re-login)

- keepalive a cada **15 min** (toque leve, só para a sessão não cair);
- leitura + diff a cada **45 min**;
- **reautenticação só quando a sessão cai de fato** — não há re-login por
  relógio. É o que menos pesa para a plataforma e menos chama anti-bot.

### Três estados, não dois

`OK_SEM_MUDANCA` · `OK_MUDOU` · **`CEGO`**. O terceiro existe porque "não
consegui ler" mascarado de "nada mudou" é falso conforto: depois de
`TUIU_SESSAO_MAX_CEGO` ciclos cegos o sistema **alarma** dizendo que o silêncio
não significa ausência de novidade. O diff também normaliza relógio/contadores
antes do hash (provado: mudança só de horário **não** gera aviso; mudança de
situação gera).

### Vigia da validade

`dias_para_expirar()` lê o `.pfx` e avisa a partir de 30 dias — a falha por
certificado vencido é silenciosa e enganosa.

### Subir / matar

```
docker compose -f ops/sessao/compose.yaml up -d --build
docker compose -f ops/sessao/compose.yaml down          # kill switch
```

Variáveis obrigatórias: `TUIU_A1_PFX_HOST` (caminho do .pfx no host) e
`TUIU_A1_PIN_FILE` (arquivo com o PIN).

## Estado atual

O mecanismo de attach está **provado**: conecta na janela, lê página do
Transferegov e **detecta corretamente quando caiu no login** (testado contra a
área de discricionárias sem sessão → `idp.transferegov.sistema.gov.br`).

Os **extratores das telas logadas ainda não existem** — nunca vimos o DOM
autenticado. Por isso o `--descobrir`: na primeira sessão real do operador ele
salva títulos, abas, tabelas e links da página logada, e a partir daí
escrevemos os extratores de pendências (diligência, complementação, prazo)
que alimentam a mesma tabela `eventos` (origem `portal`) e, daí, o notificador.

## Limites que ficam registrados

- Ler a sessão é auxílio ao operador, **não** substitui o ato pessoal dele.
- Se o portal mudar de layout, o extrator quebra — por isso o leitor guarda o
  texto bruto e a auditoria, para diagnóstico.
- Nenhuma automação de ato irreversível será adicionada a este módulo.
