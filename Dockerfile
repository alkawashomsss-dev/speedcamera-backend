FROM python:3.11-slim

WORKDIR /app

# Force no cache - timestamp: 2026-01-08-21-05
RUN pip install --no-cache-dir tenacity==8.2.3 aiohttp==3.9.1 requests==2.31.0 httpx==0.25.2 fastapi==0.104.1 "uvicorn[standard]==0.24.0" pymongo==4.6.1 python-dotenv==1.0.0 motor==3.3.2 pydantic==2.5.2

COPY server.py .

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
