# LabLens: FastAPI service + built React frontend in one container (Hugging Face Spaces, port 7860).

FROM node:22.11.0-slim AS frontend
WORKDIR /build
COPY openapi.yaml ./
COPY evals/results_ml.json evals/results_critical.json evals/results_extract_dev.json evals/results_explain_dev.json ./evals/
COPY frontend/package.json frontend/package-lock.json ./frontend/
# The lockfile is made on macOS, so add the Linux native bundler binding at the locked version.
RUN cd frontend && npm ci \
 && V=$(node -p "require('rolldown/package.json').version") && A=$(node -p "process.arch") \
 && npm install --no-save "@rolldown/binding-linux-$A-gnu@$V"
COPY frontend ./frontend
RUN cd frontend && npm run build

FROM python:3.11.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LABLENS_CACHE_DIR=/tmp/lablens-cache \
    LABLENS_FRONTEND_DIST=/app/frontend/dist
RUN useradd -m -u 1000 app
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY reference ./reference
COPY models ./models
COPY data/case_specs.yaml ./data/case_specs.yaml
COPY data/reports/source ./data/reports/source
COPY data/ground_truth/D*.json ./data/ground_truth/
COPY --from=frontend /build/frontend/dist ./frontend/dist
# Some source files are owner-only on the build machine; the app runs as a non-root user.
RUN chmod -R a+rX /app
USER app
EXPOSE 7860
# Behind nginx: take the client IP from X-Forwarded-For so per-IP rate limits apply per visitor.
# Safe because the container port is published on 127.0.0.1 only.
CMD ["uvicorn", "lablens.api.app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "7860", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
