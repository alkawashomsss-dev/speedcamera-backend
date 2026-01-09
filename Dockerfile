FROM python:3.11-slim

WORKDIR /app

# CACHEBUST v3
ARG CACHEBUST=v3_20260108_2305

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Set default env vars
ENV MONGO_URL=mongodb://localhost:27017
ENV DB_NAME=speedcamera
ENV PORT=8001

EXPOSE 8001

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001}"]
