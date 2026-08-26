FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/ubuntu/requirements-server.txt ./deploy/ubuntu/requirements-server.txt
RUN python -m pip install --no-cache-dir -r deploy/ubuntu/requirements-server.txt

COPY . .

EXPOSE 8000

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000", "--public-demo"]
