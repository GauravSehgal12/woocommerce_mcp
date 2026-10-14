# Kubernetes deployment guide

This repository uses the same `helm/woo-platform` chart for Kind and k3s. Environment-specific images, Ingress hosts/classes, and storage behavior live in values files. No VPS is required for local development.

## Workload layout

- `woo-frontend`: dashboard, ClusterIP service on port 80.
- `woo-platform-wordpress`: WordPress/WooCommerce service on port 80, installed as a separate Helm release.
- `woo-agent`: chat agent on port 8300.
- `woo-gateway`: MCP gateway on port 8100.
- `woo-registry-api`: registry API on port 8101.
- `woo-mcp-service`: WooCommerce MCP server on port 8000.
- `gateway-data`: persistent volume shared by the gateway and registry. Keep both at one replica while they share this ReadWriteOnce volume and file-backed state.
- WordPress uploads/content and MariaDB data must use their own persistent claims from the WordPress Helm release.

The application chart configures readiness/liveness probes and resource requests/limits for all five application Deployments. The WordPress and MariaDB Deployments are managed by the separate Bitnami WordPress chart; keep that chart's built-in probes enabled and configure explicit requests/limits and persistence in its values for each environment.

## Secrets

Never commit credentials, populated `.env` files, Kubernetes Secret YAML containing real values, or tokens. The application chart expects:

- Secret `woo-agent-secrets`, with `GROQ_API_KEY` (and any additional environment variables the agent needs).
- Secret `woocommerce-api-credentials`, with `WOOCOMMERCE_CONSUMER_KEY` and `WOOCOMMERCE_CONSUMER_SECRET`.

Example PowerShell setup. Set the values in your own shell first; do not paste them into source files or commit them:

```powershell
$env:GROQ_API_KEY = Read-Host "Groq API key"
$env:WOOCOMMERCE_CONSUMER_KEY = Read-Host "WooCommerce consumer key"
$env:WOOCOMMERCE_CONSUMER_SECRET = Read-Host "WooCommerce consumer secret"

kubectl create namespace woo-platform --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic woo-agent-secrets -n woo-platform `
  --from-literal=GROQ_API_KEY="$env:GROQ_API_KEY" `
  --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic woocommerce-api-credentials -n woo-platform `
  --from-literal=WOOCOMMERCE_CONSUMER_KEY="$env:WOOCOMMERCE_CONSUMER_KEY" `
  --from-literal=WOOCOMMERCE_CONSUMER_SECRET="$env:WOOCOMMERCE_CONSUMER_SECRET" `
  --dry-run=client -o yaml | kubectl apply -f -

Remove-Item Env:GROQ_API_KEY, Env:WOOCOMMERCE_CONSUMER_KEY, Env:WOOCOMMERCE_CONSUMER_SECRET
```

Run secret creation only after confirming that the expected keys match the application code and existing secret requirements. Do not replace working secrets blindly. Kubernetes Secret objects are base64-encoded by default, not encrypted by that encoding; enable encryption at rest and restrict RBAC for production.

## Local Kind Ingress and stable URLs

The local values use the NGINX Ingress class and the hosts `dashboard.localhost` and `store.localhost`. The `.localhost` suffix resolves to loopback in modern browsers/operating systems. Since this existing Kind cluster was not created with host port mappings, use a port-forward to the Ingress controller rather than recreating the cluster.

Install the ingress-nginx controller into the existing Kind cluster:

```powershell
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx `
  --namespace ingress-nginx --create-namespace `
  --set controller.service.type=ClusterIP --wait --timeout 5m
```

In a separate PowerShell window, keep this running:

```powershell
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
```

Deploy/update the application chart after verifying the current local release and PVCs:

```powershell
helm lint .\helm\woo-platform
helm template woo-apps .\helm\woo-platform -n woo-platform -f .\helm\woo-platform\values-kind.yaml
helm upgrade --install woo-apps .\helm\woo-platform `
  --namespace woo-platform `
  --values .\helm\woo-platform\values-kind.yaml `
  --wait --timeout 5m
```

Then browse to:

- Dashboard: http://dashboard.localhost:8080
- Storefront: http://store.localhost:8080

If your browser does not resolve `.localhost` subdomains, add these entries to the Windows hosts file (`C:\Windows\System32\drivers\etc\hosts`) as administrator:

```text
127.0.0.1 dashboard.localhost
127.0.0.1 store.localhost
```

Do not delete the Kind cluster or its PVCs to set up Ingress. The chart sets `gatewayDataPvc.create: false` locally because the existing `gateway-data` claim is managed separately and must be preserved.

## k3s / VPS deployment

The production values use the Traefik Ingress class, which is normally bundled with k3s, and set `gatewayDataPvc.create: true` for the gateway/registry data claim. The default production hosts are examples only; replace them with DNS names you control before deploying and configure TLS.

1. Point DNS records for the dashboard and store hostnames to the VPS public IP.
2. Install k3s and verify `kubectl get nodes` reports Ready.
3. Create the two Kubernetes Secrets described above in the `woo-platform` namespace.
4. Install WordPress/WooCommerce and MariaDB in that same cluster using the WordPress chart, with persistent claims and explicit resource requests/limits. Ensure its Service is named `woo-platform-wordpress` or override `wooMcp.storeUrl` accordingly.
5. Install the app chart:

```bash
helm lint ./helm/woo-platform
helm template woo-apps ./helm/woo-platform -n woo-platform -f ./helm/woo-platform/values-k3s.yaml
helm upgrade --install woo-apps ./helm/woo-platform \\
  --namespace woo-platform --create-namespace \\
  --values ./helm/woo-platform/values-k3s.yaml \\
  --set ingress.dashboardHost=dashboard.YOUR_DOMAIN \\
  --set ingress.storeHost=store.YOUR_DOMAIN \\
  --wait --timeout 10m
```

6. Configure TLS for the Ingress hosts (for example with cert-manager and a trusted issuer), firewall only the required ports, and set up backups for WordPress uploads, MariaDB, and `gateway-data`.

Do not run the production command against the local Kind context. Check `kubectl config current-context` first. A VPS is only needed when you are ready to test the remote k3s deployment.

## Pre-deployment verification

```powershell
kubectl config current-context
kubectl get nodes
kubectl get pods -n woo-platform
kubectl get pvc -n woo-platform
kubectl get ingress -n woo-platform
helm list -n woo-platform
```

Verify all application Pods are Ready, all required PVCs are Bound, the Ingress controller is healthy, and test chat tool invocation against actual WooCommerce data. For the WordPress release, also verify its MariaDB and WordPress claims and probe/resource configuration.
