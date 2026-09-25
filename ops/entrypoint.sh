#!/usr/bin/env bash
# Ponto de entrada da imagem do Tuiú — uma imagem, vários papéis:
#
#   console   espera o banco, aplica as migrações e sobe o uvicorn (padrão)
#   cadeia    ops/rodar_diario.py  — elo a elo, para no vermelho (quem chama é o xyOps)
#   sonda     ops/sonda_atualizacao.py — mede a hora da carga (quem chama é o timer systemd)
#   testes    pytest — SÓ contra banco descartável (serviço `testes` do compose)
#   outro     executa como comando: ex. `python ferramentas/usuario.py --criar ...`
set -euo pipefail
cd /app

migrar() {
  python -c "import sys; sys.path.insert(0, 'backend'); from app.db import migrar; print('migrações:', migrar() or 'nenhuma nova', flush=True)"
}

papel="${1:-console}"
case "$papel" in
  console)
    python ops/esperar_banco.py
    migrar
    # 0.0.0.0 é DENTRO do container; o compose publica só em 127.0.0.1:8600 do host
    # (o console mostra dado de organizações reais — publicar é decisão do dono, via cloudflared).
    exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8600
    ;;
  cadeia)
    shift; python ops/esperar_banco.py
    exec python ops/rodar_diario.py "$@"
    ;;
  sonda)
    shift
    exec python ops/sonda_atualizacao.py "$@"
    ;;
  testes)
    shift; python ops/esperar_banco.py
    exec pytest "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
