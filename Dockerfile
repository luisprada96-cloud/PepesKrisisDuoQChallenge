FROM python:3.12-slim

WORKDIR /app

# Copy application files
COPY . /app

EXPOSE 8085

CMD ["python", "server.py"]
