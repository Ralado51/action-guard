# Imagem da aplicacao (backend + interface). NAO e a imagem do executor isolado,
# que fica em sandbox/ e infra/ e nao recebe credenciais.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements-dev.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "web.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
