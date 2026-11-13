FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY . .
ARG AUREON_BUILD_COMMIT=unknown
ENV AUREON_BUILD_COMMIT=${AUREON_BUILD_COMMIT}
ENV PYTHONPATH=/app
ENV AUREON_CONTENT_HASH_FILE=/app/IMAGE_CONTENT_HASH
# Bake the ops/, desk/, and requirements-lock.txt digest. This is not the commit label.
RUN python -c "from ops.content_hash import write_baked; write_baked('/app/IMAGE_CONTENT_HASH')"
EXPOSE 8080
# One process. The in-memory rate limit and the file locks assume a single web worker.
# python -m ops.app remains the local listener. Production does not use it.
CMD ["gunicorn", "--workers", "1", "--threads", "1", "--bind", "0.0.0.0:8080", "ops.app:app"]
