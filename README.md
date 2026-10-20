# WooCommerce MCP Platform

A local Kubernetes-based platform for connecting WooCommerce and supporting services to AI agents through the **Model Context Protocol (MCP)**. The project brings together a WooCommerce store, MCP tools, an authenticated gateway, a registry/dashboard, and an AI agent for multi-step workflows.

> **Project status:** Development and testing. The commands and local URLs below reflect the current local Kind setup and may need adjustment for another environment. Review security and operational configuration before deploying to production.

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Key capabilities](#key-capabilities)
- [Technology stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Local Kubernetes setup](#local-kubernetes-setup)
- [Access the application](#access-the-application)
- [Example workflows](#example-workflows)
- [Security and audit checks](#security-and-audit-checks)
- [Troubleshooting](#troubleshooting)
- [Data safety](#data-safety)

## Overview

The platform is designed to let an AI agent use tools exposed by multiple MCP servers while keeping access behind a gateway. WooCommerce provides the store and order-management layer, while separate inventory and shipping services demonstrate cross-server tool use.

### Architecture

```text
                         +----------------------+
                         | Dashboard / Frontend |
                         |    woo-frontend      |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Registry API         |
                         | woo-registry-api     |
                         +----------------------+

+----------------+       +----------------------+       +----------------------+
| AI Agent       |------>| MCP Gateway          |------>| WooCommerce MCP      |
| woo-agent      |       | woo-gateway          |       | woo-mcp-service      |
+-------+--------+       +----------------------+       +----------+-----------+
        |                                                          |
        |                                                          v
        |                                              +------------------------+
        |                                              | WordPress + WooCommerce |
        |                                              | MariaDB                |
        |                                              +------------------------+
        |
        +--------------------> Inventory MCP service
        |
        +--------------------> Shipping MCP service
```

This diagram is conceptual. Actual network routes, registered servers, and tool names depend on the repository's current configuration.

## Key capabilities

- Expose WooCommerce operations through MCP tools.
- Route authenticated MCP requests through a gateway.
- Register and manage MCP servers through a dashboard/registry.
- Inspect tool activity in the audit log.
- Use inventory and shipping tools together in a single agent workflow.
- Create WooCommerce products and verify their actual status in the store admin.
- Create pending orders through the MCP order workflow; this workflow does **not** process payment.
- Test storefront checkout with Cash on Delivery (COD), when enabled in WooCommerce.
- Run the local stack on Kubernetes using Kind and Helm.

## Technology stack

- **Store:** WordPress and WooCommerce
- **Database:** MariaDB
- **MCP services and agent:** Python-based services (see the source code for exact dependencies)
- **Containerization:** Docker
- **Local Kubernetes:** Kind and `kubectl`
- **Packaging/deployment:** Helm
- **Gateway, registry, and dashboard:** Project-specific services in this repository

## Prerequisites

Install and configure:

- Docker Desktop (with its container engine running)
- WSL 2, if required by your Docker Desktop setup
- `kubectl`
- Kind
- Helm
- Git
- Python and a virtual environment if you run services or tests locally

Verify the command-line tools:

```powershell
docker version
kubectl version --client
kind version
helm version
git --version
```

## Local Kubernetes setup

Run commands from the repository root in PowerShell.

### 1. Check the existing cluster

Check first to avoid creating a duplicate cluster:

```powershell
kind get clusters
kubectl config current-context
kubectl get nodes
```

The local environment described by this README uses the Kind cluster `woo-platform` and context `kind-woo-platform`.

For a **fresh environment only**, after confirming the cluster does not already exist:

```powershell
kind create cluster --name woo-platform
kubectl config use-context kind-woo-platform
kubectl create namespace woo-platform
```

### 2. Configure secrets

Create the Kubernetes Secrets expected by the current Helm chart and application configuration before deployment. Check the chart values to identify the exact secret names and keys:

```powershell
Get-Content .\helm\woo-platform\values-kind.yaml
Get-ChildItem .\helm\woo-platform -Recurse
```

Use your own strong passwords and API keys. Do not commit real credentials, `.env` files containing secrets, or secret values in YAML files.

### 3. Inspect and deploy with Helm

The local Kind values file used by this setup is:

```text
helm/woo-platform/values-kind.yaml
```

Inspect the release and render the chart before making changes:

```powershell
helm list -n woo-platform
helm template woo-apps .\helm\woo-platform `
  -n woo-platform `
  -f .\helm\woo-platform\values-kind.yaml
```

For an **existing** release, the following upgrade pattern was used in this environment:

```powershell
helm upgrade woo-apps .\helm\woo-platform `
  -n woo-platform `
  -f .\helm\woo-platform\values-kind.yaml `
  --server-side=true `
  --force-conflicts
```

Only set image overrides when the matching image has been built and loaded into Kind. Check the current values and release before upgrading; do not uninstall the release as a routine troubleshooting step.

### 4. Verify workloads

```powershell
kubectl get pods -n woo-platform
kubectl get services -n woo-platform
kubectl get deployments -n woo-platform
```

Check a rollout using the actual deployment name shown by `kubectl get deployments`:

```powershell
kubectl rollout status deployment/woo-mcp-service -n woo-platform
kubectl rollout status deployment/woo-agent -n woo-platform
kubectl rollout status deployment/woo-platform-wordpress -n woo-platform
```

Deployment names may vary with chart values.

## Access the application

If the NGINX ingress controller and corresponding host rules are configured, start this port-forward in a dedicated PowerShell terminal and leave it running:

```powershell
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
```

Local URLs used by this setup:

- **Storefront:** <http://store.localhost:8080>
- **WordPress Admin:** <http://store.localhost:8080/wp-admin>
- **Dashboard:** <http://dashboard.localhost:8080>

These URLs require the ingress rules and local hostname resolution to be configured.

To access the gateway directly, if the service exposes port `8100`:

```powershell
kubectl port-forward -n woo-platform svc/woo-gateway 8100:8100
```

The local MCP endpoint used in this setup is:

```text
http://127.0.0.1:8100/mcp
```

Use the configured API key header (for example, `X-API-Key`) when making authenticated requests. Never place a real API key in this README or source control.

## Example workflows

### Inventory and shipping in one request

The agent can use the inventory and shipping MCP services in the same workflow. Example request:

> Check stock for SKU `MOUSE-001` and calculate the shipping cost for delivery to Gurgaon, Haryana, India. Use both the inventory and shipping tools. If you need the package weight, dimensions, or origin, ask me instead of guessing.

Provide missing shipping details when requested. Cost and delivery estimates depend on the tool implementation and the supplied inputs.

### Product creation

The intended agent behavior is to publish a normal product by default unless the user explicitly requests another supported status. Verify the status returned by the tool and confirm it in WooCommerce Admin; do not assume a product is published merely because the agent says it is.

### MCP order creation

The `create_order` MCP workflow creates a pending order and does **not** process payment. Verify the order in WooCommerce Admin. A pending MCP-created order is not proof that storefront checkout or payment has completed.

### Cash on Delivery checkout

1. Open the storefront.
2. Add a published product to the cart.
3. Enter the checkout details.
4. Select **Cash on delivery (COD)** if it is enabled.
5. Place the order once.
6. In WordPress Admin, open **WooCommerce → Orders** and verify the payment method, products, quantity, total, and order status.

A successful COD checkout validates the storefront checkout path. It does not, by itself, validate every MCP order workflow.

## Security and audit checks

- Use a dedicated test API key for revocation tests.
- Revoke the test key through the dashboard, then retry a request with that key and confirm it is rejected (for example, HTTP `401`).
- Check the audit log for the rejected attempt if rejected requests are configured to be recorded.
- Confirm audit events show the relevant user, server/tool, timestamp, duration, and outcome where those fields are available.
- Do not share API key values in logs, screenshots, or issue reports.

## Troubleshooting

### Pods are not ready

```powershell
kubectl get pods -n woo-platform -o wide
kubectl describe pod <pod-name> -n woo-platform
kubectl logs <pod-name> -n woo-platform --tail=100
kubectl get events -n woo-platform --sort-by=.lastTimestamp
```

Replace `<pod-name>` with the real pod name.

### Deployment is not rolling out

```powershell
kubectl get deployments -n woo-platform
kubectl rollout status deployment/<deployment-name> -n woo-platform
kubectl describe deployment <deployment-name> -n woo-platform
```

### Port-forward fails

```powershell
kubectl get services -n woo-platform
kubectl get pods -n woo-platform
```

Check the service's actual ports and confirm the target pods are ready. Keep the port-forward process running while using the forwarded URL.

### WordPress or database issue

```powershell
kubectl get deployments,statefulsets,pvc -n woo-platform
kubectl logs deployment/woo-platform-wordpress -n woo-platform --tail=100
kubectl logs statefulset/woo-platform-mariadb -n woo-platform --tail=100
```

Resource names can vary by chart; confirm them before running commands.

## Data safety

**Do not delete persistent volume claims (PVCs) as a routine troubleshooting step.** The local environment may store WordPress files and MariaDB data on PVCs. Deleting a PVC can permanently remove store data.

For a recovery test, deleting a disposable pod or temporarily scaling a test deployment can demonstrate Kubernetes recovery, but it may temporarily make that service unavailable. Restore the desired replica count afterward and wait for the pod to become ready. Avoid scaling down WordPress, MariaDB, or core gateway services unless you intentionally plan and understand the impact.

## Repository layout

Key paths referenced by this setup include:

```text
.
├── app/
│   └── agent/
│       └── agent_api.py
├── helm/
│   └── woo-platform/
│       └── values-kind.yaml
└── woo-mcp-service/
    └── server.py
```

Additional frontend, gateway, registry, test-service, Docker, and test files may exist. Inspect the current repository tree for the complete structure.

## Development guidelines

- Keep credentials in environment variables or Kubernetes Secrets.
- Use a dedicated test key for revocation tests.
- Review changes with `git diff` before committing.
- Stage only intended files if other work is uncommitted; avoid `git add .` when you want to commit only the README.
- Verify actual deployment names, ports, secret names, image tags, and tool schemas against the current configuration.
- Test changes in the local Kind environment before considering a production deployment.
