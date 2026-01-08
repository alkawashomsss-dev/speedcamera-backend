FROM python:3.11-slim

WORKDIR /app

# Cache buster - change this to force rebuild
ARG CACHEBUST=8

# Copy and install requirements (no cache)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir tenacity aiohttp requests && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY server.py .

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
