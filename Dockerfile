FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend

# Tasks live in /data. Mount a persistent volume here in production.
RUN mkdir -p /data
ENV HOST=0.0.0.0 \
    PORT=8000 \
    ORION_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 8000
WORKDIR /app/backend
CMD ["python", "server.py"]
