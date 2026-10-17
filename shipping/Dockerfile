FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "mcp>=1.0.0,<2.0.0"
COPY shipping_server.py .
EXPOSE 8300
CMD ["python", "shipping_server.py"]