FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POKERED_SOURCE_ROOT=/source/pokered \
    POKEMON_THREE_D_CONFIG=/app/data/config/three_d.json \
    POKEMON_ASSETS_PATH=/app/assets

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY tools ./tools
COPY data/config ./data/config
COPY assets ./assets

RUN pip install --no-cache-dir . \
    && addgroup --system game \
    && adduser --system --ingroup game game

USER game
EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
