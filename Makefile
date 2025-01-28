.PHONY: check format test bootstrap

# Check if Poetry is installed
poetry := $(shell command -v poetry 2>/dev/null)
ifeq ($(poetry),)
$(error Poetry is not installed or not in the current PATH)
endif

# Check if Git is installed
git := $(shell command -v git 2>/dev/null)
ifeq ($(git),)
$(error Git is not installed or not in the current PATH)
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

re-tag:
	git push --delete origin refs/tags/$(TAG) &&\
	git tag --delete $(TAG) &&\
	git tag $(TAG) &&\
	git push --tags

# Helper function to bump version, commit, and tag
bump-version:
	@poetry version $(PART)
	@VERSION=$$(poetry version -s); \
	git add pyproject.toml; \
	git commit -m "Bump version to $$VERSION";

# Targets for different version increments
bump-patch:
	@$(MAKE) PART=patch bump-version

bump-minor:
	@$(MAKE) PART=minor bump-version

bump-major:
	@$(MAKE) PART=major bump-version

bump-release:
	@$(MAKE) PART=release bump-version

bump-prepatch:
	@$(MAKE) PART=prepatch bump-version

bump-preminor:
	@$(MAKE) PART=preminor bump-version

bump-premajor:
	@$(MAKE) PART=premajor bump-version

bump-prerelease:
	@$(MAKE) PART=prerelease bump-version

new-tag:
	@VERSION=$$(poetry version -s); \
	git tag -a "v$$VERSION" -m "Version $$VERSION" &&\
	git push --tags &&\
	echo "Pushed tag v$$VERSION" ||\
	echo "Failed to push tag v$$VERSION"

package:
	poetry build && poetry publish