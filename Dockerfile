FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8080

# Unprivilegierter Benutzer; /data gehört ihm, damit ein benanntes Volume beschreibbar ist.
RUN apk add --no-cache tzdata \
 && addgroup -g 1000 app \
 && adduser -D -H -u 1000 -G app app \
 && mkdir -p /data \
 && chown app:app /data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY app ./app

USER app
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/healthz', timeout=3)"

CMD ["python", "-m", "app"]
