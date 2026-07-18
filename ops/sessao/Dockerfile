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

# A imagem base traz os BINÁRIOS dos navegadores em /ms-playwright, mas não o
# pacote Python do Playwright — por isso ele é instalado aqui, na mesma versão
# dos binários (1.59.0), senão o cliente reclama de versão.
# psycopg p/ gravar eventos; cryptography p/ ler a validade do A1.
RUN pip install --no-cache-dir --break-system-packages \
        "playwright==1.59.0" "psycopg[binary]==3.3.3" cryptography

# código: apenas os módulos de leitura/notificação (nada de assinatura)
COPY backend/app/ /app/backend/app/
COPY ingest/portal/ /app/ingest/portal/

# A pasta de saída precisa EXISTIR e ser do `leitor` já no build: um volume
# nomeado herda a dona do diretório da imagem: se ela não existir, o volume
# nasce como root e o container (não-root) não consegue escrever.
RUN mkdir -p /app/data/sessao \
    && useradd -m -u 10001 leitor \
    && chown -R leitor:leitor /app
USER leitor

# Sem porta exposta: o container não serve nada, só lê e avisa.
CMD ["python", "ingest/portal/sessao_loop.py"]
