IMAGE ?= action-guard

.PHONY: test run docker-build docker-test docker-run

test:            ## testes locais (precisa de requirements-dev.txt instalado)
	python -m pytest -q

run:             ## API local em http://localhost:8000
	uvicorn web.app.main:app --reload --port 8000

docker-build:
	docker build -t $(IMAGE) .

docker-test: docker-build   ## roda a suite dentro da imagem (Python 3.12)
	docker run --rm $(IMAGE) python -m pytest -q

docker-run: docker-build    ## sobe a API; credenciais vem de --env-file, nunca da imagem
	docker run --rm -p 8000:8000 --env-file .env $(IMAGE)
