FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
COPY config ./config
RUN pip install --no-deps --no-build-isolation -e .
USER 1000:1000
CMD ["uvicorn", "qarevin.api:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
