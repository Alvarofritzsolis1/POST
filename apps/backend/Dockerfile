FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_THREAD_LIMIT=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
    postgresql-client libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY apps/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/backend/app ./app
# git checkout de despliegue utiliza umask 077: el contexto puede contener
# archivos 0600 y directorios 0700. COPY preserva esos permisos.
# Dejar el código legible (no escribible) para UID 10001 sin relajar permisos
# de secretos ni modificar el checkout o volúmenes del VPS.
RUN chmod -R a+rX /srv/app
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin galant
USER galant
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
