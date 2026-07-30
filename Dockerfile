FROM python:3.13-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir \
    pandas openpyxl typer rich readchar fastapi uvicorn

# Copy app
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Data directory for volumes
VOLUME /app/data/all_reservations

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

CMD ["python", "-m", "villa_matcher.cli", "serve", "--host", "0.0.0.0", "--port", "8080"]
