# Use a stable Python base
FROM python:3.10-slim

WORKDIR /app

# system deps for typical builds (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# When running under Fly, it sets $PORT. Our Flask app uses 5000 by default; we forward accordingly.
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4"]
