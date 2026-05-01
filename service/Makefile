.PHONY: dev prod verify install

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

prod:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2

verify:
	cd .. && python3 test_pz_regression.py --e2e
