# Imagem do Tuiú — uma só para o console, a cadeia diária, a sonda, os testes e as
# ferramentas de linha de comando (o papel é escolhido pelo entrypoint).
#
# Regras da casa que este arquivo faz valer:
#   - a base vem do REGISTRO LOCAL do araticum (nunca do Docker Hub): ARG com padrão
#     localhost:5000/base/...; e sem linha `# syntax=` (ela buscava no Hub a cada build);
#   - roda como usuário sem privilégio, uid 1000 = `pedro` no host, para os bind
#     mounts de data/ e ops/logs/ continuarem legíveis e graváveis dos dois lados;
#   - nenhum segredo entra na imagem: o .env do host é montado em runtime (env_file);
#   - o modelo de embedding do guia NÃO é baixado no build: vive no volume `modelos`
#     (FASTEMBED_CACHE_PATH) e é aquecido no deploy, uma vez.
ARG PYTHON_IMAGE=localhost:5000/base/python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/cache/fastembed \
    HF_HOME=/cache/huggingface

WORKDIR /app

# dependências primeiro: mudança de código não reinstala nada
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# o mesmo recorte que o tar do deploy antigo levava para o host
COPY backend/ /app/backend/
COPY ingest/ /app/ingest/
COPY ferramentas/ /app/ferramentas/
COPY db/ /app/db/
COPY testes/ /app/testes/
COPY ops/rodar_diario.py ops/sonda_atualizacao.py ops/relatorio_mensal.py ops/esperar_banco.py ops/entrypoint.sh /app/ops/
# os scripts de deploy entram só porque a suíte os lê (teste_varredura_dados registra a barreira do smoke)
COPY ops/deploy_araticum.sh ops/deploy_remoto.sh /app/ops/
COPY pytest.ini /app/pytest.ini

# data/ e ops/logs/ são bind mounts; /cache é o volume do modelo. Os três precisam
# existir e pertencer ao usuário JÁ NA IMAGEM: um volume nomeado herda a dona do
# diretório da imagem — se nascer como root, o container (não-root) não escreve.
ARG UID=1000
RUN useradd -m -u ${UID} tuiu \
    && mkdir -p /app/data /app/ops/logs /cache \
    && chmod +x /app/ops/entrypoint.sh \
    && chown -R tuiu:tuiu /app /cache
USER tuiu

EXPOSE 8600
ENTRYPOINT ["/app/ops/entrypoint.sh"]
CMD ["console"]
