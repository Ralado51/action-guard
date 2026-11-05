# Separate evaluator image. Never copy the backend, .env, run evidence or credentials.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir jsonschema==4.23.0 referencing==0.37.0
COPY contracts /app/contracts
COPY engine /app/engine
COPY sandbox/worker.py /app/worker.py
COPY sandbox/probe.py /app/probe.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
ENTRYPOINT ["python", "-I", "/app/worker.py"]
