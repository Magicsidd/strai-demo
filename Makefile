PY := .venv/bin/python

.PHONY: demo test seed nullstill installer katalog

demo:
	./demo.sh

installer:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

katalog:
	$(PY) -m katalog.bygg

test: katalog/elementer.json
	$(PY) -m pytest -q

katalog/elementer.json:
	$(PY) -m katalog.bygg

seed:
	$(PY) -m demo.seed

nullstill:
	$(PY) -m demo.seed --nullstill
