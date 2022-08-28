.PHONY: help
help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
.DEFAULT_GOAL := help

run-yaml-lint:
	yamllint ansible/

run-ansible-lint: install-ansible
	ansible-lint ansible/

install-ansible: req-galaxy ## Install roles via ansible-galaxy
	@echo "Installing roles via ansible-galaxy"
	ansible-galaxy install -r ansible/requirements.yaml -f

configure-ansible: req-playbook ## Run ansible
	@echo "Run ansible-playbook"
	ansible-playbook ansible/site.yml -i ansible/inventory/pik8s/hosts.ini

req-galaxy:
	@command -v ansible-galaxy >/dev/null 2>&1 || { echo >&2 "require ansible-galaxy"; exit 1; }

req-playbook:
	@command -v ansible-playbook >/dev/null 2>&1 || { echo >&2 "require ansible-playbook"; exit 1; }
