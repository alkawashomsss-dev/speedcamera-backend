FROM python:3.11-slim

# CACHE BUSTER - Railway must rebuild after this
ARG CACHEBUST=20260108_2135_v1

WORKDIR /app

# Force fresh install with unique timestamp
RUN echo "Cache bust: 20260108_2135_v1" && \
    pip install --no-cache-dir --force-reinstall \
    tenacity \
    aiohttp \
    requests \
    httpx \
    fastapi \
    "uvicorn[standard]" \
    pymongo \
    python-dotenv \
    motor \
    pydantic

COPY server.py /app/server.py

RUN python -c "import tenacity; print('SUCCESS: tenacity installed')"

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
