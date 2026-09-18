FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml alembic.ini ./
COPY apps/backend ./apps/backend
RUN pip install --no-cache-dir --no-deps . && useradd -m -u 10001 clipbot && mkdir -p /app/data/media /app/data/sources && chown -R clipbot:clipbot /app
USER clipbot
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn clipbot.api:app --host 0.0.0.0 --port 8000"]
