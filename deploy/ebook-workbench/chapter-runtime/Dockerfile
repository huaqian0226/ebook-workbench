FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS compiler
WORKDIR /compiler
RUN python -c "import base64,hashlib,io,tarfile,urllib.request; data=urllib.request.urlopen('https://registry.npmjs.org/typescript/-/typescript-6.0.3.tgz',timeout=60).read(); assert base64.b64encode(hashlib.sha512(data).digest()).decode()=='y2TvuxSZPDyQakkFRPZHKFm+KKVqIisdg9/CZwm9ftvKXLP8NRWj38/ODjNbr43SsoXqNuAisEf1GdCxqWcdBw=='; tarfile.open(fileobj=io.BytesIO(data),mode='r:gz').extract('package/lib/typescript.js',filter='data')"
FROM ghcr.io/bookorbit/bookorbit@sha256:507a84c08c100244c27bce68ce59670da5dc8c3bc9054dd4aea3630977c42885 AS build
WORKDIR /work
COPY --from=compiler /compiler/package/lib/typescript.js /work/typescript.cjs
COPY *.ts build.cjs ./
RUN node build.cjs
FROM ghcr.io/bookorbit/bookorbit@sha256:507a84c08c100244c27bce68ce59670da5dc8c3bc9054dd4aea3630977c42885
COPY --from=build /work/out/ /app/dist/modules/book-request/fulfillment/
COPY public/ /app/public/
ENV APP_VERSION=3.10.0-workbench.0.3.0
LABEL org.opencontainers.image.source="https://github.com/huaqian0226/ebook-workbench" org.opencontainers.image.revision="workbench-v0.3.0"
