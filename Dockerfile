FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yt-dlp curl-cffi requests websockets

WORKDIR /app

COPY server.py .

RUN mkdir -p /app/downloads

ENV PYTHONUNBUFFERED=1
ENV PORT=8765

EXPOSE 8765

CMD ["python", "server.py"]