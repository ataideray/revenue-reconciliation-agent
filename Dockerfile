# Imagem do agente para o Azure Container Apps (decisão de 2026-10-15).
# Só o código e o destinos.json (semente do cadastro) entram na imagem: os
# dados reais, os vínculos confirmados e as chaves ficam fora (.dockerignore).
# Os dados ficam no Azure Files, montado em /dados.
FROM python:3.12-slim-bookworm

# pdftotext (poppler-utils) lê os PDFs; tzdata para o horário de Brasília
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Sao_Paulo \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CF_AGENTE_DIR=/dados/agente \
    CF_CADASTROS_DIR=/dados/cadastros

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[agente]" && rm -rf build
COPY cadastros/destinos.json /app/semente/destinos.json

# sem root: o Azure Files é montado com uid/gid 1000 (veja docs/azure.md)
RUN useradd --uid 1000 --create-home agente && mkdir -p /dados && chown agente /dados
USER agente

EXPOSE 8000
# na 1ª vez, o cadastro de destinos vem da semente; depois, fica o do volume
CMD ["sh", "-c", "mkdir -p \"$CF_AGENTE_DIR\" \"$CF_CADASTROS_DIR\" && cp -n /app/semente/destinos.json \"$CF_CADASTROS_DIR/\"; exec conselho-fiscal agente --host 0.0.0.0 --porta 8000 --sem-simulador --cadastros-reais --pasta \"$CF_AGENTE_DIR\""]
