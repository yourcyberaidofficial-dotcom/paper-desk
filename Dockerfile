FROM python:3.12-slim
WORKDIR /app
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY . .
ARG AUREON_BUILD_COMMIT=unknown
ENV AUREON_BUILD_COMMIT=${AUREON_BUILD_COMMIT}
ENV PYTHONPATH=/app
EXPOSE 8080
CMD ["python", "-m", "ops.app"]
