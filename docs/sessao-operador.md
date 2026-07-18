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
