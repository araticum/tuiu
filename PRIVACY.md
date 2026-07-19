# PRIVACY — Tuiú

Controlador: **Araticum Comércio e Serviços Especializados LTDA** — CNPJ 62.762.410/0001-27
Canal do titular: **adm@araticumcomercio.com.br** (resposta em até 15 dias — LGPD art. 19)

Aplica o gate transversal `D:\Quimera\PRIVACY.md`. Dado pessoal de **fonte pública**
(Transferegov, SICONV/detru, Portal da Transparência) **continua sendo dado pessoal** —
LGPD art. 7º §§3º–4º.

Papel do Tuiú: a Araticum é **operadora** dos dados dos clientes (executa o Transferegov em
nome deles) e **controladora** dos dados dos próprios usuários do console.

---

## §2 — Gate de concepção (respondido)

### Feature: console multi-tenant + autenticação (19/07/2026)

1. **Processa dado pessoal?** Sim: login e nome dos operadores, IP e user-agent de acesso,
   CPF e nome de dirigentes de OSC (MROSC), texto livre do diário de atendimento e — antes da
   correção abaixo — nome de beneficiário de pagamento vindo do extrato bancário da g2.
2. **Finalidade e base legal:** operar o Transferegov em nome do cliente
   (**execução de contrato**, art. 7º V) e controlar quem acessa o console
   (**interesse legítimo**, art. 7º IX, com o mínimo necessário).
3. **Dá para entregar o mesmo valor com menos dado?** Sim, e foi feito: o nome do
   beneficiário do extrato **não tem finalidade** aqui — usamos contagem de lançamentos e
   saldo. Passou a ser mascarado na entrada, e os 3.796 registros já gravados foram
   remediados (`ferramentas/mascarar_recortes.py`).
4. **Onde, quem acessa, retenção:** tabela abaixo.
5. **Sai do ambiente?** Consulta a **CEPIM/CEIS/CNEP** (Portal da Transparência/CGU) enviando
   **apenas o CNPJ** do cliente — nada de PF. Nenhum envio a LLM. Nenhum envio a Meta/WhatsApp
   (canais de notificação **pausados**, ver `configuracoes`).
6. **É sensível ou de menor?** Não. Se um dia entrar dado de saúde de beneficiário final de
   projeto (a carteira tem hospitais), **parar e desenhar salvaguarda antes** — hoje o Tuiú
   não toca nisso.

---

## §4 — Registro de operações (ROPA)

| Dado | Onde | Finalidade | Base legal | Retenção | Quem acessa | Sai p/ terceiro? |
|---|---|---|---|---|---|---|
| login, nome do operador | `usuarios` | acesso ao console | interesse legítimo | enquanto a conta existir; conta inativa expurga em 5 anos | operador | não |
| senha (hash scrypt + sal) | `usuarios.senha_hash` | autenticação | interesse legítimo | idem | ninguém (irreversível) | não |
| IP, user-agent | `sessoes`, `acessos_log` | segurança do acesso, freio de força bruta | interesse legítimo | sessão: 7 d após expirar · tentativa: 180 d | operador | não |
| **CPF MASCARADO** e nome de dirigente (PF) | `clientes_pessoas` | conferir impedimento do dirigente (MROSC — dirigente impedido contamina a entidade) | execução de contrato | enquanto durar a relação + 5 anos | operador e o próprio cliente | **sim** — o NOME vai ao Portal da Transparência (CGU); o CPF completo **não temos** |
| CNPJ, razão social, UF, município | `clientes` | identificar quem atendemos | execução de contrato | idem | operador e o próprio cliente | sim — CNPJ à CGU |
| texto livre de atendimento | `diario_cliente` | histórico do serviço prestado | execução de contrato | idem | operador | não |
| nome de beneficiário de pagamento | `data/recortes/**/extrato-bancario.jsonl.gz` | **nenhuma** | — | **mascarado na entrada desde 19/07/2026** | — | não |
| e-mail reencaminhado do Transferegov | `eventos` (origem `inbox`) | captar recado privado do portal | execução de contrato | 5 anos | operador | não |

**CPF de dirigente: guardamos apenas o MASCARADO** (`***790718**`, 6 dígitos), como vem do dado
aberto da Receita — não obtemos nem armazenamos o documento completo (D1: menos dado para o
mesmo valor). A consulta de sanção passou a ser por **nome**, e os dígitos visíveis servem só
para descartar homônimo; sanção com o mesmo nome e sem CPF no registro vira `a_confirmar` para
decisão humana, nunca impedimento automático.

**Dado que deliberadamente NÃO coletamos:** senha gov.br de cliente (impersonação descartada —
ver `docs/sessao-operador.md`), CAUC do ente (é do ente, fora de escopo), dado de beneficiário
final dos projetos.

---

## §3 — Como os defaults aparecem no código

- **D3 deny by default:** `auth.escopo()` devolve conjunto **vazio** para papel desconhecido —
  papel novo nasce sem alcance. O middleware fecha toda rota que não esteja na lista pública, e
  usuário `cliente` só alcança `ROTAS_CLIENTE`. Provado em `testes/teste_auth.py`
  (isolamento entre tenants e papéis inventados).
- **Trava no banco também:** `usuarios_escopo_ck` impede papel `cliente` sem `doc_cliente` —
  o filtro "só o meu" não pode degenerar em "sem filtro".
- **D6 cripto:** senha em `scrypt` (n=2¹⁴, sal de 16 bytes por usuário), comparação por
  `hmac.compare_digest`. Segredos no cofre DPAPI / `.env` 600 no host, nunca no git.
- **D5 log limpo:** senha nunca é impressa, logada nem passada por argumento de linha de
  comando (`ferramentas/usuario.py` sorteia e grava em arquivo 600).
- **Inventário grepável:** `grep -r "pii:" db/` lista as colunas marcadas (§3 do gate).
- **D4 retenção:** view `expurgo_pendente` mostra o que passou do prazo.

---

## §5 — Direitos do titular (art. 18)

**Exportar tudo que temos de um titular** (dirigente PF, por CPF):

```sql
SELECT 'clientes_pessoas' AS origem, to_jsonb(p) FROM clientes_pessoas p WHERE p.cpf = :cpf
UNION ALL
SELECT 'diario_cliente', to_jsonb(d) FROM diario_cliente d WHERE d.texto ILIKE '%' || :cpf || '%';
```

**Exportar de um usuário do console** (por login):

```sql
SELECT 'usuarios' AS origem, to_jsonb(u) - 'senha_hash' FROM usuarios u WHERE u.login = :login
UNION ALL SELECT 'acessos_log', to_jsonb(a) FROM acessos_log a WHERE a.login = :login
UNION ALL SELECT 'sessoes',     to_jsonb(s) - 'token' FROM sessoes s WHERE s.login = :login;
```

**Apagar** (art. 18 VI — respeitando a guarda legal da prestação de contas, que é obrigação
legal e prevalece enquanto durar):

```sql
DELETE FROM clientes_pessoas WHERE cpf = :cpf;      -- dirigente
DELETE FROM usuarios WHERE login = :login;          -- cascata mata sessoes
DELETE FROM acessos_log WHERE login = :login;
```

**Expurgo periódico** (rodar quando `expurgo_pendente` acusar):

```sql
DELETE FROM sessoes     WHERE expira_em < now() - interval '7 days';
DELETE FROM acessos_log WHERE quando    < now() - interval '180 days';
```

---

## §6 — Incidentes

Nenhum registrado até 19/07/2026.

**Quase-incidente corrigido em 19/07/2026:** o recorte da g2 gravava em disco o **nome
completo** de beneficiários de pagamento das OSCs (o CPF vem mascarado da fonte, o nome não),
sem finalidade declarada — 3.796 registros em 53 arquivos no host. Mascarado na entrada
(`recorte_ente._sem_nome_pf`) e remediado no acervo existente
(`ferramentas/mascarar_recortes.py`, verificado: 0 restantes). Não houve acesso indevido; os
arquivos nunca saíram do host nem foram expostos por API.
