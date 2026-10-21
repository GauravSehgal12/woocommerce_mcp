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
- [REST API and MCP rationale](#why-rest-for-administration-and-mcp-for-tools)
- [Upstream credentials and server editing](#upstream-credentials-and-server-editing)
- [Timeouts and error handling](#timeouts-and-upstream-errors)
- [Tool naming and collisions](#tool-naming-and-collision-handling)
- [k3s / production-like deployment](#k3s--production-like-deployment)
- [Known limitations](#known-limitations)
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


## Why REST for administration and MCP for tools?

The platform uses **REST endpoints for control-plane operations**—such as registering, editing, enabling/disabling, and removing servers; managing users and API keys; and querying health or audit logs. These operations map naturally to HTTP resource semantics, browser-based forms, status codes, and role-based authorization.

The gateway exposes discovered upstream capabilities through **MCP** so compatible agents and clients can list and call tools using the MCP protocol. In short: REST manages the platform; MCP carries tool discovery and invocation.

## Upstream credentials and server editing

Administrators can configure custom upstream HTTP headers when registering a server and update server metadata or credentials through the admin-only endpoint:

```http
PATCH /servers/{server_id}
Content-Type: application/json
```

Example request body (replace the placeholder with a credential from your secret manager; never commit a real token):

```json
{
  "description": "Inventory MCP server",
  "headers": {
    "Authorization": "Bearer <UPSTREAM_TOKEN>"
  }
}
```

Omitted fields remain unchanged. To replace the configured header set, send a new `headers` object. Use an empty object to clear custom headers. Header values are intentionally omitted from server-list, health, create, update, enable, and disable responses; responses include only whether headers are configured and their names. The endpoint is admin-only and validates header names and values.

**Credential storage limitation:** in this implementation, upstream header values are stored in the gateway's registry JSON file. Protect that file and its persistent volume with restrictive permissions and backups. For production, prefer a secrets manager or Kubernetes Secret references and avoid storing raw credential values in ordinary registry JSON.

## Timeouts and upstream errors

- Tool invocation has a **10-second overall timeout**.
- Upstream tool discovery and available-tool listing use a **5-second overall timeout**.
- Timeout failures are reported separately from an unreachable upstream server. Check the URL, DNS, network policies, TLS configuration, and upstream availability when a server is reported unreachable.
- Timeouts bound the gateway's wait; they do not guarantee that a remote operation has been rolled back. For non-idempotent upstream actions, verify the remote state before retrying after a timeout.

## Tool naming and collision handling

Discovered tools normally use the readable name `<server_name>__<tool_name>`. If two upstream entries would produce a case-insensitive name collision, the gateway adds a deterministic suffix derived from the upstream server's ID, for example:

```text
inventory__check_stock__a1b2c3d4
```

The suffix is derived from the registered server ID, not a credential. Registering a server with a duplicate name is rejected. If a collision suffix changes after a server's identity or registration changes, refresh the client's discovered tool list.

## k3s / production-like deployment

The repository includes `helm/woo-platform/values-k3s.yaml` as a starting point for a k3s environment. Before deploying:

1. Build and publish the required container images to a registry accessible by the k3s nodes, then set immutable or versioned image tags in the values file.
2. Configure Kubernetes Secrets for application keys, WooCommerce API credentials, database passwords, and LLM provider keys. Do not commit secrets or put them directly in Helm values.
3. Review storage classes and PVCs. The sample values use the `local-path` storage class for gateway data; ensure your k3s cluster has a suitable storage provisioner and a backup/restore plan.
4. Set resource requests/limits and replicas based on expected traffic. Test upgrades and rollbacks in a staging namespace first.
5. Use TLS, network policies, restricted service accounts, and a supported secret-management strategy before exposing the services publicly.
6. Verify the actual chart values and deployment names before applying changes.

Example template/upgrade commands (run from the repository root):

```bash
helm template woo-apps ./helm/woo-platform \
  --namespace woo-platform \
  -f ./helm/woo-platform/values-k3s.yaml

helm upgrade --install woo-apps ./helm/woo-platform \
  --namespace woo-platform \
  --create-namespace \
  -f ./helm/woo-platform/values-k3s.yaml
```

These commands render/install the chart; they do not provision DNS, TLS certificates, external databases, or cloud secrets automatically.

### Ingress approach

The Helm chart uses a Kubernetes Ingress resource to route the dashboard and storefront by host name. The local Kind values use the NGINX ingress class and local hostnames; the sample k3s values use Traefik and example hostnames. Configure DNS records to point to the ingress controller, and configure TLS certificates through your chosen certificate workflow (for example, cert-manager) before using public hostnames. Keep the gateway and registry management endpoints private unless they are deliberately exposed behind appropriate authentication and network controls.

## Known limitations

- This is a development-oriented platform, not a fully audited production service.
- Custom upstream headers are currently persisted in the gateway registry JSON file; use a secret manager or Secret references for production.
- The gateway rate limiter is in-memory and per process. Multiple replicas need a shared limiter or ingress-level rate limiting for a global quota.
- The registry and health status are file-backed. Concurrent writers, multi-replica deployments, and recovery require additional coordination and durable storage design.
- Timeout errors do not prove that an upstream mutation did not occur; verify state before retrying non-idempotent calls.
- Tool discovery depends on upstream MCP servers being reachable and compatible with the configured Streamable HTTP transport.
- The sample k3s values are a starting point and do not constitute complete production hardening, high availability, monitoring, backups, or disaster recovery.
- Storefront COD checkout and MCP-created pending orders are separate workflows and should be tested independently.

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
