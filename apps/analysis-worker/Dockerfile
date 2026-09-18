FROM python:3.10.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/analysis-worker

# Questo file definisce l'immagine container del worker. Non alimenta una
# pagina del sito direttamente, ma rende possibile il processo background che
# aggiorna Cronologia, Dettaglio analisi, Dashboard e Stato del sistema.
RUN groupadd --gid 999 --system appgroup \
    && useradd --uid 999 --gid 999 --system --create-home --home-dir /home/appuser appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Oltre al codice applicativo vengono incluse anche le regole YARA, perché la
# pipeline malware deve poterle compilare all'avvio del processo.
COPY app ./app
COPY rules ./rules

USER appuser

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/health').status == 200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
