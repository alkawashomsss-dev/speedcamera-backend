FROM python:3.11-slim

WORKDIR /app

# Install ALL dependencies directly - NO CACHE
RUN pip install --no-cache-dir \
    tenacity>=8.0.0 \
    aiohttp>=3.9.0 \
    requests>=2.31.0 \
    httpx>=0.25.0 \
    fastapi>=0.104.0 \
    uvicorn[standard]>=0.24.0 \
    pymongo>=4.6.0 \
    python-dotenv>=1.0.0 \
    motor>=3.3.0 \
    pydantic>=2.5.0

# Copy app
COPY server.py /app/server.py

# Verify tenacity is installed
RUN python -c "import tenacity; print('tenacity OK')"

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
