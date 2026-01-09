FROM python:3.11-slim

WORKDIR /app

# CACHEBUST v2
ARG CACHEBUST=v2_20260108_2255

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

RUN python -c "import tenacity; print('SUCCESS: tenacity installed')"

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
