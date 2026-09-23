# Operação do Tuiú no araticum

Desde 23/09/2026 o Tuiú roda **inteiro em container** no host `araticum` (`10.0.0.42`),
decisão do dono: a infra da casa é toda Docker. Antes (19/07 a 23/09) era venv +
`systemd --user`; só o banco era container. Nada de dado mudou de lugar.

## O que roda onde

| Peça | Como | Onde vê |
|---|---|---|
| Console (API + telas) | container `tuiu-console`, uvicorn, publicado **só em `127.0.0.1:8600`** do host; o cloudflared do host publica `tuiu.araticum.net` | `docker compose -f ops/compose.yaml logs -f console` |
| Banco | container `tuiu-db` (Postgres 16), volume **`ops_tuiu_pgdata`** (o mesmo desde 19/07), `127.0.0.1:25432` | `docker exec tuiu-db psql -U postgres tuiu` |
| Cadeia diária (09:30) | evento **`tuiu_diario` do xyOps** → `docker compose run --rm -T cadeia` | job no xyOps (`:5522`) e `ops/logs/diario-<data>.log` |
| Sonda da hora de carga | **timer `systemd --user`** (`ops/systemd/`) → `docker compose run --rm -T sonda` | `systemctl --user list-timers tuiu-sonda.timer`, `ops/logs/sonda-atualizacao.jsonl` |
| Modelo do guia (fastembed) | volume `tuiu_modelos`, aquecido no deploy | `docker volume inspect tuiu_modelos` |
| Segredos | `/home/pedro/tuiu/.env` (chmod 600, fora do git), montado por `env_file` | nunca na imagem nem no tar |
| Dados | bind mounts: `data/` → `/app/data`, `ops/logs/` → `/app/ops/logs` | `du -sh /home/pedro/tuiu/data` |

Tudo está em [`compose.yaml`](compose.yaml); a imagem é [`Dockerfile`](Dockerfile) (base
`localhost:5000/base/python:3.12-slim`, do registro local — nunca do Docker Hub) e o
papel de cada container é escolhido pelo [`entrypoint.sh`](entrypoint.sh).

## Deploy

Da máquina de desenvolvimento, com o código commitado que se quer em produção:

```bash
bash ops/deploy_araticum.sh                # build + testes + sobe + agendamentos
bash ops/deploy_araticum.sh --sem-testes   # pula o pytest
```

O local só manda o tar (com CRLF normalizado); [`deploy_remoto.sh`](deploy_remoto.sh) faz
o resto **no host** e é idempotente. Os testes rodam contra um Postgres **descartável**
(`db-teste`, tmpfs) — nunca contra o banco real: `teste_auth.py` mexe em contas e
`smoke_eventos.py` apaga tabela inteira. Teste vermelho interrompe o deploy antes de
tocar a produção.

## Dia a dia (no host, em `/home/pedro/tuiu`)

```bash
docker compose -f ops/compose.yaml ps
docker compose -f ops/compose.yaml logs -f console
docker compose -f ops/compose.yaml run --rm -T cadeia              # rodar a cadeia agora
docker compose -f ops/compose.yaml run --rm -T cadeia --sem-radar  # flags do rodar_diario.py
docker compose -f ops/compose.yaml run --rm -T sonda --resumo      # o que a sonda já mediu
docker compose -f ops/compose.yaml restart console
docker compose -f ops/compose.yaml down                            # para tudo; volume fica
```

Ferramentas de linha de comando rodam dentro da imagem. A senha inicial de uma conta é
gravada em `/app/.senha-inicial-<login>` — que morre com o container —, então leia no
mesmo comando:

```bash
docker compose -f ops/compose.yaml run --rm -T console bash -c 'python ferramentas/usuario.py --criar LOGIN --nome "Nome" && cat .senha-inicial-LOGIN'
```

## Por que a sonda ficou no systemd e a cadeia foi para o xyOps

A regra da casa (04/08/2026) é: automação nasce no xyOps — histórico, alerta, Catch-Up e
a janela de sono do host (02:30 → 05:30). A cadeia diária é exatamente isso, e o evento
`tuiu_diario` termina com `pipe_metric.sh`, como os outros pipes do host: métrica para o
watchdog das 08:00 e WhatsApp da equipe na transição ok→falha / falha→ok.

A sonda bate de 10 em 10 minutos de manhã (~72 vezes por dia): é **medição**, não
automação — exceção 3 da mesma regra. No xyOps ela empurraria o histórico dos pipes que
importam (a tabela de jobs é capada em 100.000 linhas). O timer está versionado em
[`systemd/`](systemd/) e o deploy o instala; `Persistent=true` recupera a batida perdida
no boot das 05:30.

## Rollback

O corte guardou as units antigas em `~/tuiu-systemd-aposentado-<data>/` e o venv
`/home/pedro/tuiu/.venv` ainda existe. Voltar: `docker compose -f ops/compose.yaml stop
console`, copiar as units de volta para `~/.config/systemd/user/`, `systemctl --user
daemon-reload && systemctl --user enable --now tuiu-console.service tuiu-diario.timer`, e
desabilitar o evento `tuiu_diario` no xyOps. O banco é o mesmo volume nos dois modelos.
