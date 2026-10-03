# ACRFP — multi-stage Distroless image
#
# Builder: full Python tooling to install packages.
# Runtime: Google Distroless (no shell, no apt, no package manager).
# Python 3.11 matches gcr.io/distroless/python3-debian12.
#
# IMPORTANT: use --ignore-installed with --prefix so deps already present on the
# builder image (e.g. packaging) are still copied into /install for Distroless.

FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

COPY requirements-prod.txt .
RUN pip install --no-cache-dir --prefix=/install --ignore-installed -r requirements-prod.txt \
    && python -c "import sys; sys.path.insert(0,'/install/lib/python3.11/site-packages'); import packaging, uvicorn; print('ok', packaging.__version__, uvicorn.__version__)"

COPY src ./src
COPY data ./data

FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/local/lib/python3.11/site-packages:/app/src

COPY --from=builder /install /usr/local
COPY --from=builder /build/src /app/src
COPY --from=builder /build/data /app/data

EXPOSE 8000

# Distroless ENTRYPOINT is python3 (no bash). Module form is required.
CMD ["-m", "uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
