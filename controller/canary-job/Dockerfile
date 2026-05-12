FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY promote.py .
ENTRYPOINT ["python", "/app/promote.py"]
