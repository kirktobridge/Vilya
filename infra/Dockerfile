FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry==1.8.3
ENV POETRY_VIRTUALENVS_CREATE=false

# Install Python deps first (layer cache)
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --without dev

# Copy source
COPY src/ ./src/
COPY db/ ./db/

# Prometheus metrics port
EXPOSE 8000

CMD ["python", "-m", "src.execution.loop"]
