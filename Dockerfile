FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY server/ ./server/
COPY inference.py .
COPY openenv.yaml .

RUN python src/data_generator.py data

EXPOSE 8000

ENV PORT=8000
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
