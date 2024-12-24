export PROJECTNAME=$(shell basename "$(PWD)")
VENV_PATH=./.venv/bin

.SILENT: ;               # no need for @

setup: ## Setup Virtual Env
	uv venv
	$(VENV_PATH)/python3 -m pip install --upgrade pip

deps: ## Install dependencies
	uv tool install pre-commit

pre-commit: ## Manually run all precommit hooks
	uv tool run pre-commit

pre-commit-tool: ## Manually run a single pre-commit hook
	$(VENV_PATH)/pre-commit run $(TOOL) --all-files

clean: ## Clean package
	find . -type d -name '__pycache__' | xargs rm -rf
	rm -rf build dist

.PHONY: help
.DEFAULT_GOAL := help

help: Makefile
	echo
	echo " Choose a command run in "$(PROJECTNAME)":"
	echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
	echo
