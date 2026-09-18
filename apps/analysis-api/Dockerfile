FROM python:3.10.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/analysis-api

# Questo file definisce l'immagine container della Analysis API. Non serve una
# pagina del sito, ma rende possibile eseguire localmente e in futuro fuori dal
# Mac lo stesso backend che alimenta Dashboard, Cronologia, Profilo e API auth.
#
# L'utente non root riduce l'impatto di eventuali bug applicativi o dipendenze.
RUN groupadd --gid 999 --system appgroup \
    && useradd --uid 999 --gid 999 --system --create-home --home-dir /home/appuser appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Si copiano solo artefatti runtime essenziali: codice applicativo, migrazioni
# e script di bootstrap del container.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh

RUN chmod +x /srv/analysis-api/entrypoint.sh

USER appuser

EXPOSE 8000

# Il probe HTTP locale è coerente con quello usato dall'infrastruttura e
# verifica reachability della replica senza dipendere da tool extra nel container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)" || exit 1

CMD ["./entrypoint.sh"]
