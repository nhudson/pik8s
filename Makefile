.PHONY: help
help: ## This help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
.DEFAULT_GOAL := help

run-yaml-lint:
	yamllint provision/ansible

run-ansible-lint: install-ansible
	ansible-lint -c .ansible-lint.yaml provision/ansible

install-ansible: req-galaxy ## Install roles via ansible-galaxy
	@echo "Installing roles via ansible-galaxy"
	ansible-galaxy install -r provision/ansible/requirements.yaml -f

configure-ansible: req-playbook ## Run ansible
	@echo "Run ansible-playbook"
	ansible-playbook provision/ansible/playbooks/k3s-install.yml -i provision/ansible/inventory/hosts.yml

reset-ansible: req-playbook
	@echo "Reset ansible-playbook"
	ansible-playbook provision/ansible/playbooks/k3s-reset.yml -i provision/ansible/inventory/hosts.yml

req-galaxy:
	@command -v ansible-galaxy >/dev/null 2>&1 || { echo >&2 "require ansible-galaxy"; exit 1; }

req-playbook:
	@command -v ansible-playbook >/dev/null 2>&1 || { echo >&2 "require ansible-playbook"; exit 1; }
