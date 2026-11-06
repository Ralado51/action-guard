FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY contracts ./contracts
COPY engine ./engine
COPY connector ./connector
COPY orchestrator ./orchestrator
COPY planner ./planner
COPY audit ./audit
COPY acceptance ./acceptance
COPY calibration ./calibration
COPY vultr_agent ./vultr_agent
COPY web ./web
COPY infra/start.py /app/start.py
RUN useradd --create-home --uid 10001 appuser
USER 10001:10001
EXPOSE 8000
CMD ["python", "/app/start.py"]
