# syntax=docker/dockerfile:1
# Plainread web app with Tesseract OCR. The image never needs internet access at runtime.

FROM python:3.15-slim AS build
WORKDIR /src
COPY . .
ARG BUILD_NUMBER=docker
ARG COMMIT=unknown
RUN python scripts/stamp_build.py --build-number "${BUILD_NUMBER}" --commit "${COMMIT}" \
 && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.15-slim
ARG BUILD_NUMBER=docker
ARG COMMIT=unknown
LABEL org.opencontainers.image.title="Plainread" \
      org.opencontainers.image.description="Explain hard letters in plain language, privately, on your own device." \
      org.opencontainers.image.source="https://github.com/lobojoel2003/Plainread" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${COMMIT}" \
      io.plainread.build-number="${BUILD_NUMBER}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa tesseract-ocr-osd \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 plainread

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

USER plainread
ENV PYTHONUNBUFFERED=1 \
    PLAINREAD_HOST=0.0.0.0 \
    PLAINREAD_PORT=8765
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)"
ENTRYPOINT ["plainread"]
CMD ["serve", "--no-browser"]
