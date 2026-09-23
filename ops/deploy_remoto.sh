#!/usr/bin/env bash
# Deploy do Tuiú NO HOST (araticum) — chamado pelo ops/deploy_araticum.sh depois do tar.
# Roda pelo caminho (código em arquivo, nunca em string de comando) e é idempotente:
# pode rodar de novo a qualquer hora.
#
#   1. build da imagem (base do registro local, sem Docker Hub)
#   2. testes contra Postgres DESCARTÁVEL (perfil `teste`) — pule com --sem-testes
#   3. corte do modelo antigo, se ainda existir: units systemd do venv (console e cadeia)
#      desativadas com cópia de segurança, e o `tuiu-db` recriado no projeto `tuiu`
#      (mesmo volume `ops_tuiu_pgdata`)
#   4. sobe db + console; espera saudável; fumaça
#   5. timer systemd da sonda (ops/systemd/) + evento do xyOps da cadeia (ops/xyops_eventos.py)
#   6. aquece o modelo de embedding do guia no volume `modelos` (uma vez; idempotente)
#
# Segredos continuam em /home/pedro/tuiu/.env (chmod 600): não vão no tar nem na imagem.
set -euo pipefail
cd /home/pedro/tuiu
COMPOSE=(docker compose -f ops/compose.yaml)
UNITS=~/.config/systemd/user

SEM_TESTES=0; PREPARAR=1; APLICAR=1
for a in "$@"; do
  case "$a" in
    --sem-testes)  SEM_TESTES=1 ;;
    --so-preparar) APLICAR=0 ;;    # build + testes, sem tocar a produção
    --so-aplicar)  PREPARAR=0 ;;   # corte + subir + agendar, com a imagem já construída
    *) echo "argumento desconhecido: $a" >&2; exit 2 ;;
  esac
done

"${COMPOSE[@]}" config -q          # compose inválido para aqui, antes de qualquer efeito

if [ "$PREPARAR" = 1 ]; then
  echo "==> 1. build da imagem"
  "${COMPOSE[@]}" build console
else
  echo "==> 1. build pulado (--so-aplicar)"
  docker image inspect tuiu-app:local >/dev/null 2>&1 || { echo "imagem tuiu-app:local não existe — rode sem --so-aplicar" >&2; exit 1; }
fi

if [ "$PREPARAR" = 0 ]; then
  echo "==> 2. testes pulados (--so-aplicar)"
elif [ "$SEM_TESTES" = 0 ]; then
  echo "==> 2. testes (Postgres descartável em tmpfs)"
  if ! "${COMPOSE[@]}" --profile teste run --rm -T testes; then
    "${COMPOSE[@]}" --profile teste rm -sf db-teste >/dev/null 2>&1 || true
    echo "TESTES FALHARAM — deploy interrompido; a produção não foi tocada." >&2
    exit 1
  fi
  "${COMPOSE[@]}" --profile teste rm -sf db-teste >/dev/null 2>&1 || true
else
  echo "==> 2. testes pulados (--sem-testes)"
fi

if [ "$APLICAR" = 0 ]; then
  echo "==> parando aqui (--so-preparar): imagem pronta e testada; produção intocada"
  exit 0
fi

echo "==> 3. corte do modelo antigo (venv + systemd + projeto compose 'ops'), se houver"
BK=~/tuiu-systemd-aposentado-$(date +%F)
for u in tuiu-console.service tuiu-diario.timer tuiu-diario.service; do
  if [ -f "$UNITS/$u" ]; then
    mkdir -p "$BK"
    systemctl --user disable --now "$u" >/dev/null 2>&1 || true
    mv "$UNITS/$u" "$BK/"
    echo "   $u desativada (cópia em $BK)"
  fi
done
systemctl --user daemon-reload
projeto=$(docker inspect tuiu-db --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)
if [ -n "$projeto" ] && [ "$projeto" != "tuiu" ]; then
  echo "   tuiu-db era do projeto '$projeto' — recriando no projeto 'tuiu' (mesmo volume ops_tuiu_pgdata)"
  docker rm -f tuiu-db >/dev/null
fi
docker volume inspect ops_tuiu_pgdata >/dev/null 2>&1 || docker volume create ops_tuiu_pgdata >/dev/null
rm -f ops/compose.db.yaml

echo "==> 4. sobe db + console"
"${COMPOSE[@]}" up -d db console
estado=none
for _ in $(seq 1 45); do
  estado=$(docker inspect tuiu-console --format '{{.State.Health.Status}}' 2>/dev/null || echo none)
  [ "$estado" = healthy ] && break
  sleep 2
done
echo "   console: $estado"
if [ "$estado" != healthy ]; then
  "${COMPOSE[@]}" logs --tail 40 console
  exit 1
fi
curl -s -o /dev/null -w "   /login.html -> %{http_code}\n" http://127.0.0.1:8600/login.html
curl -s -o /dev/null -w "   /api/cockpit sem sessão -> %{http_code} (tem que ser 401)\n" http://127.0.0.1:8600/api/cockpit

echo "==> 5. agendamentos: sonda no systemd, cadeia no xyOps"
mkdir -p "$UNITS"
cp ops/systemd/tuiu-sonda.service ops/systemd/tuiu-sonda.timer "$UNITS/"
systemctl --user daemon-reload
systemctl --user enable --now tuiu-sonda.timer >/dev/null 2>&1
loginctl enable-linger pedro >/dev/null 2>&1 || true
systemctl --user list-timers tuiu-sonda.timer --no-pager | sed -n '1,2p' | sed 's/^/   /'
python3 ops/xyops_eventos.py | sed 's/^/   /'

echo "==> 6. modelo do guia (fastembed) no volume 'modelos'"
if ! "${COMPOSE[@]}" run --rm -T console python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); print('   modelo ok')"; then
  echo "   aviso: modelo não aquecido — o console baixa no primeiro uso do guia"
fi

echo "==> pronto. Úteis:"
echo "   docker compose -f ops/compose.yaml ps"
echo "   docker compose -f ops/compose.yaml logs -f console"
echo "   docker compose -f ops/compose.yaml run --rm -T cadeia     # rodar a cadeia agora"
echo "   tail -n 40 ops/logs/diario-\$(date +%F).log"
