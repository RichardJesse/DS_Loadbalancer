FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY consistent_hash.py container_manager.py app.py .

ENV LB_MODE=docker
EXPOSE 5000

CMD ["python", "app.py"]
