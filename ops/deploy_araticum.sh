#!/usr/bin/env bash
# Deploy do Tuiú no araticum — tudo em container (desde 23/09/2026).
#
# Daqui (máquina de desenvolvimento) só sai o CÓDIGO, por tar/SSH, sem git no host
# (padrão da casa). O trabalho de verdade — build da imagem, testes, corte, subir,
# timer da sonda, evento do xyOps — é o ops/deploy_remoto.sh, que viaja no tar e
# roda LÁ pelo caminho (código em arquivo, nunca em string de comando).
#
# Segredos: continuam em /home/pedro/tuiu/.env (chmod 600); não vão no tar nem na imagem.
#
# Uso (da máquina de desenvolvimento):
#   bash ops/deploy_araticum.sh                # build + testes + sobe + agendamentos
#   bash ops/deploy_araticum.sh --sem-testes   # pula o pytest (banco descartável)
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${TUIU_HOST:-pedro@10.0.0.42}"
DESTINO="${TUIU_DESTINO:-/home/pedro/tuiu}"

# O Windows grava CRLF e o Linux engasga no \r (bash, systemd, Dockerfile). O tar sai
# de uma cópia normalizada, não da árvore de trabalho.
PALCO=$(mktemp -d)
trap 'rm -rf "$PALCO"' EXIT
tar cf - --exclude='__pycache__' --exclude='*.pyc' --exclude='ops/logs' --exclude='ops/sessao' \
  backend ingest ferramentas ops db testes pytest.ini requirements.txt .dockerignore \
  | tar xf - -C "$PALCO"
find "$PALCO" -type f \( -name '*.py' -o -name '*.sh' -o -name '*.yaml' -o -name '*.yml' -o -name '*.ini' \
  -o -name '*.txt' -o -name '*.sql' -o -name '*.service' -o -name '*.timer' -o -name 'Dockerfile' \
  -o -name '.dockerignore' -o -name '*.html' -o -name '*.js' -o -name '*.css' -o -name '*.md' \) \
  -exec sed -i 's/\r$//' {} +

echo "==> enviando código para ${HOST}:${DESTINO}"
ssh "$HOST" "mkdir -p ${DESTINO}"
tar czf - -C "$PALCO" . | ssh "$HOST" "tar xzf - -C ${DESTINO}"

echo "==> executando o deploy no host"
ssh "$HOST" bash "${DESTINO}/ops/deploy_remoto.sh" "$@"
