# Container da sessão de leitura — a "fortaleza" em volta do A1.
#
# Regras que o Dockerfile faz valer:
#   - roda como usuário SEM privilégio (não-root);
#   - NÃO copia o certificado para dentro da imagem (ele é montado :ro em runtime);
#   - NÃO instala nada de assinatura — este container só lê;
#   - o PIN chega por secret/env em runtime, nunca em camada de imagem.

FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TUIU_SESSAO_ATIVA=0

WORKDIR /app

# só o necessário para ler e avisar (psycopg p/ eventos; cryptography p/ validade do A1)
RUN pip install --no-cache-dir "psycopg[binary]==3.3.3" cryptography

# código: apenas os módulos de leitura/notificação (nada de assinatura)
COPY backend/app/ /app/backend/app/
COPY ingest/portal/ /app/ingest/portal/

RUN useradd -m -u 10001 leitor && chown -R leitor:leitor /app
USER leitor

# Sem porta exposta: o container não serve nada, só lê e avisa.
CMD ["python", "ingest/portal/sessao_loop.py"]
