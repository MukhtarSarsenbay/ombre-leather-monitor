FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth && rm -rf /var/lib/apt/lists/*
COPY app ./app
EXPOSE 8000
CMD ["sh", "-c", "exec xvfb-run -a uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
