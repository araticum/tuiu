#!/usr/bin/env bash
# Sobe tela virtual + VNC + noVNC e abre o Transferegov para o login humano.
# Quando a área autenticada for detectada, o estado é salvo no volume e o
# container encerra sozinho — a sessão fica, a tela vai embora.
set -euo pipefail

echo "[bootstrap] iniciando tela virtual ${SCREEN}"
Xvfb :99 -screen 0 "${SCREEN}" -nolisten tcp &
sleep 2

echo "[bootstrap] VNC + noVNC"
x11vnc -display :99 -forever -shared -nopw -quiet -bg >/dev/null 2>&1
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
sleep 2

echo "[bootstrap] abra no navegador:  http://localhost:6080/vnc.html"
echo "[bootstrap] (via túnel:  ssh -L 6080:127.0.0.1:6080 pedro@10.0.0.42 )"
echo "[bootstrap] faça o login gov.br na janela que aparecer."

exec python /app/ingest/portal/bootstrap_sessao.py --espera-max "${TUIU_BOOTSTRAP_ESPERA:-900}"
