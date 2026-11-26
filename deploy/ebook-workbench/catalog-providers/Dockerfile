FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY *.py /app/
RUN mkdir -p /catalog-cache && chown 65532:65532 /catalog-cache
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=180s --start-interval=3s \
  CMD ["python", "-c", "import json, os, urllib.request; port = os.environ.get('CATALOG_PORT', '8080'); data = json.load(urllib.request.urlopen('http://127.0.0.1:' + port + '/healthz', timeout=2)); raise SystemExit(data.get('status', 'ready') != 'ready')"]
CMD ["python", "serve.py"]
