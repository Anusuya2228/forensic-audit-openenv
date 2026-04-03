FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/
COPY inference.py .
COPY openenv.yaml .

# Generate synthetic data at build time so the image is self-contained
RUN python -c "import sys; sys.path.insert(0,'.'); from src.data_generator import DataGenerator; from pathlib import Path; DataGenerator(seed=42).generate_all(Path('data')); print('Data generated OK')"

EXPOSE 7860

# HF Spaces uses port 7860; override with ENV_PORT for local use
ENV PORT=7860
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
