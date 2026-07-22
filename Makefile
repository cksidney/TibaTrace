.PHONY: install check migrate test security sbom docker-build validate validate-fast validate-full

install:
	python3.11 -m venv .venv
	.venv/bin/pip install -r backend/requirements.lock -r backend/requirements-dev.lock

check:
	.venv/bin/python backend/manage.py check --settings=dawatrace.settings.test
	.venv/bin/python backend/manage.py makemigrations --check --dry-run --settings=dawatrace.settings.test

migrate:
	.venv/bin/python backend/manage.py migrate --settings=dawatrace.settings.test

test:
	.venv/bin/pytest -c backend/pytest.ini backend/tests backend/apps/prescription/tests

security:
	.venv/bin/bandit -q -r backend/apps backend/dawatrace -c pyproject.toml
	.venv/bin/pip-audit -r backend/requirements.lock

sbom:
	mkdir -p artifacts/generated/security
	.venv/bin/cyclonedx-py requirements backend/requirements.lock --output-reproducible --of JSON -o artifacts/generated/security/dawatrace-backend.cdx.json

docker-build:
	docker build --file docker/backend.Dockerfile --tag dawatrace/backend:phase3 .

validate:
	./scripts/validate_repository.sh --full

validate-fast:
	./scripts/validate_repository.sh --fast

validate-full:
	./scripts/validate_repository.sh --full


