FROM python:3.12-slim

# curl sert au healthcheck de Coolify, lancé à l'intérieur du conteneur
# ffmpeg convertit les vidéos iPhone envoyées depuis /admin/medias
RUN apt-get update && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_ENV=production
# Photos/vidéos envoyées depuis /admin/medias — volume persistant Coolify sur ce chemin
ENV UPLOAD_DIR=/app/uploads
EXPOSE 8000

# --preload : création des tables une seule fois, pas une par worker
# --timeout 300 : une vidéo envoyée depuis un téléphone en 4G peut prendre plusieurs minutes
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--preload", "--timeout", "300", "--access-logfile", "-"]
