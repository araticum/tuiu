#!/usr/bin/env bash
# Deploy do Tuiú no araticum — cópia cirúrgica, sem git no host (padrão da casa).
#
# Sobe/atualiza:
#   ~/tuiu/                       código (backend, ingest, ferramentas, ops, db)
#   banco `tuiu` no Postgres do host (migrations aplicadas na hora)
#   timer systemd --user           cadeia diária às 09h30 (pós-carga da API)
#
# NÃO encosta na stack veredas nem em nada de produção do oasis.v2.
#
# SEGREDOS: não vão no tar. O host lê de ~/tuiu/.env (chmod 600, fora do git).
#   PORTAL_TRANSPARENCIA_API_KEY   já gravado (do cofre DPAPI, via pipe)
#   TUIU_SERIEMA_*                 AUSENTE -> o aviso de cadeia quebrada não
#                                  sai do host; só fica no journal e no
#                                  `systemctl --user is-failed`. Enquanto isso,
#                                  uma quebra às 09h30 passa despercebida.
#   TUIU_IMAP_*                    ausente de propósito: o elo de inbox só liga
#                                  quando houver cadastro de operador real.
#
# Uso (da máquina de desenvolvimento):
#   bash ops/deploy_araticum.sh
set -euo pipefail

HOST="${TUIU_HOST:-pedro@10.0.0.42}"
DESTINO="${TUIU_DESTINO:-/home/pedro/tuiu}"

echo "==> enviando código para ${HOST}:${DESTINO}"
ssh "$HOST" "mkdir -p ${DESTINO}"
tar czf - backend ingest ferramentas ops db testes 2>/dev/null \
  | ssh "$HOST" "cd ${DESTINO} && tar xzf - && find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true"

echo "==> preparando ambiente"
ssh "$HOST" "bash -s" <<REMOTO
set -euo pipefail
cd ${DESTINO}

# venv próprio (não mexe no python do sistema nem no do veredas)
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
./.venv/bin/pip -q install --upgrade pip
./.venv/bin/pip -q install "psycopg[binary]" pytest
# guia: extrai texto do acervo oficial (pymupdf) e embeda local em ONNX (fastembed).
# Modelo pequeno de propósito — este host roda a produção do veredas.
./.venv/bin/pip -q install pymupdf fastembed

# Banco: container DEDICADO (não há Postgres nativo no host, e o veredas-db é
# produção do oasis.v2 — não se encosta).
docker compose -f ops/compose.db.yaml up -d >/dev/null
for i in \$(seq 1 20); do
  docker exec tuiu-db pg_isready -U postgres -d tuiu >/dev/null 2>&1 && break
  sleep 2
done
docker exec tuiu-db pg_isready -U postgres -d tuiu | sed 's/^/  /'

TUIU_DSN="postgresql://postgres@127.0.0.1:25432/tuiu" \\
  ./.venv/bin/python -c "import sys; sys.path.insert(0,'backend'); from app.db import migrar; print('  migrations:', migrar() or 'nenhuma nova')"
REMOTO

echo "==> instalando o console (systemd --user, uvicorn em loopback)"
ssh "$HOST" "bash -s" <<'REMOTO'
set -euo pipefail
mkdir -p ~/.config/systemd/user
./.venv/bin/pip -q install fastapi uvicorn 2>/dev/null || \
  (cd /home/pedro/tuiu && ./.venv/bin/pip -q install fastapi uvicorn)

cat > ~/.config/systemd/user/tuiu-console.service <<'UNIT'
[Unit]
Description=Tuiu - console de operacao (API + telas)
After=network-online.target

[Service]
WorkingDirectory=/home/pedro/tuiu
Environment=TUIU_DSN=postgresql://postgres@127.0.0.1:25432/tuiu
Environment=PYTHONUTF8=1
# 127.0.0.1 de proposito: o console mostra dado de 50 organizacoes reais.
# Publicar para fora (cloudflared) e decisao do dono, nao efeito colateral de deploy.
ExecStart=/home/pedro/tuiu/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8600
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable tuiu-console.service
# RESTART, não só enable: uvicorn não recarrega código sozinho. Sem isto o
# console segue rodando o código de quando subiu — deploy que "passou" mas
# a mudança não entrou (foi assim com RBAC, contas e base-rates até 20/07).
systemctl --user restart tuiu-console.service
sleep 2
systemctl --user is-active tuiu-console.service | sed 's/^/  console: /'
curl -s -o /dev/null -w "  /login.html -> %{http_code}\n" http://127.0.0.1:8600/login.html
curl -s -o /dev/null -w "  /api/cockpit sem sessao -> %{http_code} (tem que ser 401)\n" http://127.0.0.1:8600/api/cockpit
REMOTO

echo "==> instalando a cadeia diária (systemd --user, 09h30)"
ssh "$HOST" "bash -s" <<'REMOTO'
set -euo pipefail
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/tuiu-diario.service <<'UNIT'
[Unit]
Description=Tuiu - cadeia diaria (ingest, prazos, eventos, notificacao)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/pedro/tuiu
Environment=TUIU_DSN=postgresql://postgres@127.0.0.1:25432/tuiu
Environment=PYTHONUTF8=1
ExecStart=/home/pedro/tuiu/.venv/bin/python ops/rodar_diario.py
TimeoutStartSec=7200
UNIT

cat > ~/.config/systemd/user/tuiu-diario.timer <<'UNIT'
[Unit]
Description=Tuiu - dispara a cadeia diaria as 09h30 (apos a carga da API)

[Timer]
OnCalendar=*-*-* 09:30:00
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now tuiu-diario.timer
loginctl enable-linger pedro >/dev/null 2>&1 || true   # roda mesmo sem sessão aberta
echo "  timer instalado:"
systemctl --user list-timers tuiu-diario.timer --no-pager | head -3
REMOTO

echo "==> instalando a sonda de horário de carga (systemd --user, 04h-11h)"
ssh "$HOST" "bash -s" <<'REMOTO'
set -euo pipefail
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/tuiu-sonda.service <<'UNIT'
[Unit]
Description=Tuiu - sonda do horario de carga do Transferegov
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/pedro/tuiu
Environment=PYTHONUTF8=1
ExecStart=/home/pedro/tuiu/.venv/bin/python ops/sonda_atualizacao.py
TimeoutStartSec=300
UNIT

cat > ~/.config/systemd/user/tuiu-sonda.timer <<'UNIT'
[Unit]
Description=Tuiu - sonda o data-atualizacao a cada 10 min na janela da carga

[Timer]
# A carga cai nesta janela (detru medido as 08h13; g2 antes das 09h36). Sondar
# o dia inteiro so gastaria requisicao para reconfirmar o que ja nao muda.
OnCalendar=*-*-* 04..11:00/10:00
Persistent=false

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now tuiu-sonda.timer
echo "  timer instalado:"
systemctl --user list-timers tuiu-sonda.timer --no-pager | head -3
REMOTO

echo "==> pronto. Comandos úteis:"
echo "   ssh ${HOST} 'systemctl --user list-timers tuiu-diario.timer'"
echo "   ssh ${HOST} 'systemctl --user start tuiu-diario.service'   # rodar agora"
echo "   ssh ${HOST} 'journalctl --user -u tuiu-diario -n 50'"
echo "   ssh ${HOST} 'tail -n 40 ${DESTINO}/ops/logs/diario-\$(date +%F).log'"
echo "   ssh ${HOST} '${DESTINO}/.venv/bin/python ${DESTINO}/ops/sonda_atualizacao.py --resumo'"
echo "   ssh ${HOST} '${DESTINO}/.venv/bin/python ${DESTINO}/ferramentas/destinatario.py --listar'"
