PYTHON := venv/bin/python
PIP := venv/bin/pip
export PYTHONUNBUFFERED := 1

.PHONY: setup demo fake-demo test

setup:
	python3 -m venv venv
	$(PIP) install -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Put your OpenAI key in .env, then run: make demo"
	@echo "(No key? use: make fake-demo)"

demo:
	$(PYTHON) -m src demo

fake-demo:
	$(PYTHON) -m src demo --fake-llm

test:
	$(PYTHON) -m pytest
