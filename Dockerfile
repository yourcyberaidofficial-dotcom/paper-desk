FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt flask
COPY . .
ARG AUREON_BUILD_COMMIT=unknown
ENV AUREON_BUILD_COMMIT=${AUREON_BUILD_COMMIT}
ENV PYTHONPATH=/app
EXPOSE 8080
CMD ["python", "-m", "ops.app"]
