.PHONY: check format test bootstrap

# Check if Poetry is installed
poetry := $(shell command -v poetry 2>/dev/null)
ifeq ($(poetry),)
$(error Poetry is not installed. Please install it from https://python-poetry.org/)
endif

# Detect if the .venv exists or if pyproject.toml was edited
venv_dir := $(shell poetry env info -p)
pyproject := pyproject.toml
last_bootstrap := $(venv_dir)/.last_bootstrap

bootstrap:
	@echo "Bootstrapping the environment..."
	poetry install
	@touch $(last_bootstrap)

$(last_bootstrap): $(pyproject)
	@$(MAKE) bootstrap

check: $(last_bootstrap)
	@echo "Running ruff checks and black formatter..."
	poetry run ruff check . --fix
	poetry run black --check .

format: $(last_bootstrap)
	@echo "Formatting code with black..."
	poetry run black .

test: $(last_bootstrap)
	@echo "Running tests with pytest..."
	poetry run pytest tests/
