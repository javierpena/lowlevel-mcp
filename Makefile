.DEFAULT_GOAL := help

# Image settings (override QUAY_WORKSPACE to a different namespace)
QUAY_WORKSPACE ?= $(USER)
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "latest")
IMAGE ?= quay.io/$(QUAY_WORKSPACE)/lowlevel-mcp:$(VERSION)

export CONTAINER_ENGINE ?= podman

KUSTOMIZE_IMAGE := quay.io/REPLACE_WITH_YOUR_USERNAME/lowlevel-mcp

## container-build: Build container image
container-build:
	$(CONTAINER_ENGINE) build -t $(IMAGE) .

## container-push: Push both container images to registry
container-push:
	$(CONTAINER_ENGINE) push $(IMAGE)

## deploy-k8s: Deploy to a Kubernetes/OpenShift cluster
deploy-k8s:
	cd deploy && kustomize edit set image $(KUSTOMIZE_IMAGE)=$(IMAGE)
	kubectl apply -k ./deploy/

## undeploy-k8s: Remove deployment from Kubernetes/OpenShift
undeploy-k8s:
	kubectl delete -k ./deploy/ --ignore-not-found=true

## help: Show this help message
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@sed -n 's/^##//p' $(MAKEFILE_LIST) | column -t -s ':' | sed -e 's/^/ /'
	@echo ""
	@echo "Variables:"
	@echo "  IMAGE		        Image to build (default:  quay.io/$(QUAY_WORKSPACE)/lowlevel-mcp:$(VERSION))"
	@echo "  QUAY_WORKSPACE         Quay workspace for the image"
	@echo "  CONTAINER_ENGINE       Container engine (default: podman, can use docker)"
	@echo "  VERSION                Image tag (default: git describe or 'latest')"
