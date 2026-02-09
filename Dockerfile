FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway sets PORT environment variable
ENV PORT=8002
EXPOSE ${PORT}

CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
