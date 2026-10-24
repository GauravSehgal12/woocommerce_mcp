
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

ENV GATEWAY_HOST=0.0.0.0
ENV GATEWAY_PORT=8100

EXPOSE 8100

CMD ["python", "server.py"]