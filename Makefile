.PHONY: dev build deploy secrets-decrypt secrets-edit apply-secrets logs port-forward \
        docker-build docker-push helm-repo-add helm-package helm-push release

VERSION       ?= 1.0.0
REGISTRY      := artifactory.cloud.cms.gov/cms-devops-docker-local
HELM_REPO_URL := https://artifactory.cloud.cms.gov/artifactory/cms-devops-helm-charts
HELM_REPO_NAME := cms-devops-helm-charts

# ── Local development ─────────────────────────────────────────────────────────

dev:
	docker-compose up

# ── Docker ────────────────────────────────────────────────────────────────────

docker-build:
	docker buildx build --platform linux/amd64 -t $(REGISTRY)/devops-dashboard-backend:$(VERSION) ./backend --push
	docker buildx build --platform linux/amd64 -t $(REGISTRY)/devops-dashboard-frontend:$(VERSION) ./frontend --push

docker-push:

# ── Helm ──────────────────────────────────────────────────────────────────────

helm-repo-add:
	helm repo add $(HELM_REPO_NAME) $(HELM_REPO_URL) \
	  --username $$ARTIFACTORY_USER --password $$ARTIFACTORY_PASSWORD

helm-package:
	mkdir -p dist
	helm package helm/devops-dashboard --destination dist/

helm-push:
	helm cm-push dist/devops-dashboard-$(VERSION).tgz $(HELM_REPO_NAME)

# Combined: package the chart and push both docker images
release: docker-build docker-push helm-package helm-push

# ── Kubernetes (legacy raw manifests) ─────────────────────────────────────────

deploy:
	kubectl apply -k k8s/

secrets-decrypt:
	sops -d secrets/secrets.enc.yaml

secrets-edit:
	sops secrets/secrets.enc.yaml

apply-secrets:
	sops -d secrets/secrets.enc.yaml | kubectl apply -f -

logs:
	kubectl logs -n devops-dashboard -l app=devops-dashboard -f

port-forward:
	kubectl port-forward -n devops-dashboard svc/devops-dashboard 8080:80
