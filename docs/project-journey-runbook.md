# ACRFP Project Journey & Runbook

Hands-on record of what we built, commands we ran, issues we hit, and how we fixed them.  
**Live URL:** https://api.acrfp.site

---

## Product in one paragraph

**ACRFP** (Agentic Cloud Reliability & FinOps Platform) ingests cloud/K8s incidents, runs LangGraph agents (Diagnosis / Cost / Remediation), applies a **guardrail** (allow / require approval / deny), executes only safe paths (dry-run today), and keeps an **audit trail**. Humans approve risky actions in `/ui`.

```text
Alert → API → Agents → Guardrail → Executor (or /ui approval) → Audit
```

---

## Phase map

| Phase | Goal | Status |
|-------|------|--------|
| 1 Local | Run API + guardrail + executor on PC (`mock` LLM) | Done |
| 2 AKS | Same app on Azure Kubernetes + public HTTPS | Done |
| 3 Foundry | Real LLM via Azure AI Foundry | Pending |

---

## Phase 1 — Local (commands)

### Start services (3 terminals)

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:Path = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;" + $env:Path

# Terminal A — API
$env:PYTHONPATH = "src"
$env:LLM_PROVIDER = "mock"
$env:ACRFP_MODE = "local"
$env:EXECUTOR_URL = "http://127.0.0.1:8002"
$env:GUARDRAIL_URL = "http://127.0.0.1:8001"
.\.venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8010

# Terminal B — Executor
$env:PYTHONPATH = "src"
$env:ACRFP_MODE = "local"
.\.venv\Scripts\python.exe -m uvicorn executor.app:app --host 127.0.0.1 --port 8002

# Terminal C — Guardrail
$env:PYTHONPATH = "src"
$env:POLICY_PACK = "local"
.\.venv\Scripts\python.exe -m uvicorn guardrail.app:app --host 127.0.0.1 --port 8001
```

### Health + ingest

```powershell
Invoke-RestMethod http://127.0.0.1:8010/health
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health

$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\ingest_samples.py http://127.0.0.1:8010
```

### Local URLs

- UI: http://127.0.0.1:8010/ui  
- Docs: http://127.0.0.1:8010/docs  
- Health: http://127.0.0.1:8010/health  

---

## Phase 2 — AKS deploy (commands)

### Start cluster (after it was stopped for cost)

```powershell
$env:Path = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;" + $env:Path
az account show --query "{name:name, user:user.name}" -o table
az aks start --resource-group acrfp-rg --name acrfp-aks
```

**Check running:**

```powershell
az aks show -g acrfp-rg -n acrfp-aks --query "{name:name, powerState:powerState.code}" -o table
# Want: powerState = Running
```

### Get kubectl credentials

```powershell
az aks get-credentials --resource-group acrfp-rg --name acrfp-aks --overwrite-existing
```

**What this does:** downloads cluster login into `~/.kube/config` so `kubectl` talks to AKS.

### Verify node, pods, services, ingress

```powershell
kubectl get nodes
kubectl get pods
kubectl get svc
kubectl get ingress
kubectl get svc -n ingress-nginx ingress-nginx-controller
kubectl get pods -n ingress-nginx
```

**Healthy signals:**
- Node `Ready`
- `acrfp-api`, `acrfp-guardrail`, `acrfp-executor` pods `Running` (ignore old 18d `Unknown`/`Completed` leftovers)
- Ingress host `api.acrfp.site` with ADDRESS = nginx EXTERNAL-IP
- Services are `ClusterIP` (public entry is Ingress, not each Service)

---

## Platform install explained (`install_aks_platform.ps1`)

This script does **not** deploy ACRFP app pods. It installs the **shared cluster platform** with **Helm**.

### What each part did (Aug 2026 recreate)

| Step in output | What it is | Why we need it |
|----------------|------------|----------------|
| Helm already installed | Helm CLI on your PC | Package manager for Kubernetes |
| `helm repo add` + `update` | Chart catalogs (ingress-nginx, jetstack, argo) | Where Helm downloads install packages from |
| `helm upgrade --install ingress-nginx` | nginx Ingress Controller | **Public front door** (LoadBalancer + HTTP routing by hostname) |
| Azure health-probe annotation `/healthz` | LB health check path | Without this, Azure marks nginx unhealthy → ports 80/443 timeout |
| `helm upgrade --install cert-manager` | Certificate automation | Talks to Let's Encrypt, creates TLS secrets |
| ClusterIssuers staging + prod | Who can request certs | Staging = test (untrusted); prod = real browser-trusted HTTPS |
| `helm upgrade --install argocd` | GitOps control plane | Later: sync app from Git (optional for demos) |
| Ingress LoadBalancer IP | Public IP of the gate | DNS `api.acrfp.site` must point here |

**Current nginx EXTERNAL-IP after recreate:** `20.219.215.219`  
(Always re-check: `kubectl get svc -n ingress-nginx ingress-nginx-controller`)

### What is Helm? (interview + memory)

**Helm = apt/yum for Kubernetes.**  
A **chart** = folder of templates + default values.  
A **release** = one installed instance of a chart on the cluster.

| Command | Meaning |
|---------|---------|
| `helm repo add <name> <url>` | Register a chart store |
| `helm repo update` | Refresh chart versions |
| `helm upgrade --install <release> <chart>` | Install if missing, upgrade if present (idempotent) |
| `helm list -A` | Show all releases |
| `helm status <release> -n <ns>` | One release details |
| `helm uninstall <release> -n <ns>` | Remove a release |

**How you used Helm already:**
1. Platform: `ingress-nginx`, `cert-manager`, `argocd` via `install_aks_platform.ps1`
2. App (next): `helm upgrade --install acrfp infra/helm/acrfp -f infra/helm/acrfp/values-ingress.yaml`

**Interview line:**  
> “I use Helm for platform add-ons and for the ACRFP app chart. `upgrade --install` keeps deploys repeatable.”

---

## How end customers reach the app (Ingress + HTTPS)

### Path

```text
Customer browser
   │  types https://api.acrfp.site/ui
   ▼
GoDaddy DNS  →  A record api = nginx public IP (e.g. 20.219.215.219)
   ▼
Azure Load Balancer (ports 80 + 443)
   ▼
nginx Ingress Controller  →  looks at Host header api.acrfp.site
   ▼
Service acrfp-api (ClusterIP)  →  only inside cluster
   ▼
Pod acrfp-api  →  FastAPI (/ui, /docs, /health, /v1/*)
```

### Why this design

| Piece | Public? | Role |
|-------|---------|------|
| App Services (`ClusterIP`) | No | Internal only — safer |
| nginx Ingress (`LoadBalancer`) | Yes | One gate for many apps/hosts |
| cert-manager + Let's Encrypt | — | Free trusted TLS certificate |
| DNS `api.acrfp.site` | Yes | Human-friendly name → gate IP |

**Customers never need kubectl, your laptop, or port-forward.**  
They only need the URL while AKS is **Running** and DNS points at the current Ingress IP.

### HTTPS specifically

1. Ingress asks cert-manager for a cert for `api.acrfp.site` (`letsencrypt-prod`).
2. Let's Encrypt proves you control the name (HTTP-01 challenge on port 80).
3. cert-manager stores cert in Secret `acrfp-api-tls`.
4. nginx terminates TLS → forwards HTTP to the ClusterIP Service.

**Port-forward** (`kubectl port-forward ...`) is only for **you** debugging. It is **not** the customer path.

### DNS checklist after every new Ingress IP

1. `kubectl get svc -n ingress-nginx ingress-nginx-controller` → note EXTERNAL-IP  
2. GoDaddy → `acrfp.site` → A record **Name `api`** → that IP  
3. Wait for DNS: `nslookup api.acrfp.site`  
4. Then TLS can issue / renew

### Option A — prove app via port-forward (AKS, not local uvicorn)

```powershell
kubectl port-forward svc/acrfp-api 8010:80
```

Open: http://127.0.0.1:8010/health and http://127.0.0.1:8010/ui  

**Why:** private tunnel PC → AKS Service → pod. No DNS/TLS required.

### Option B — public URL

```powershell
nslookup api.acrfp.site
curl.exe https://api.acrfp.site/health
```

Open: https://api.acrfp.site/ui · https://api.acrfp.site/docs · https://api.acrfp.site/health

---

## Issues we hit and how we fixed them

### 1) Azure CLI login blocked (`AADSTS530035`)

**Symptom:** `az login` failed; Security Defaults blocked Azure CLI.  
**Fix:** In Entra ID → Properties → Manage security defaults → **Disabled** (dev/personal tenant). Then:

```powershell
az login --use-device-code --tenant "f5cad4a6-1265-48be-9af0-b8e0a91ebd42"
```

Use **Salman’s Chrome profile** (device code), not the wrong default Chrome profile.

### 2) Wrong Chrome profile opens during `az login`

**Symptom:** Login went to Satwik account / no subscriptions.  
**Fix:** Prefer `--use-device-code` and complete login in the Chrome profile already signed into Azure Portal.

### 3) Public HTTPS timeout (ports 80/443)

**Symptom:** DNS OK, but Let's Encrypt challenge timed out; `Test-NetConnection` to LB IP failed.  
**Root cause:** Azure Load Balancer health probe for nginx was failing.  
**Fix:** Annotate nginx Service health probe path:

```powershell
helm upgrade ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --reuse-values `
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz
```

Also ensure NSG inbound rules use **Source port `*`**, destination `80`/`443` (not source port 80).

### 4) Staging TLS — browser “Not secure” / curl `SEC_E_UNTRUSTED_ROOT`

**Symptom:**

```text
curl https://api.acrfp.site/health
→ schannel: SEC_E_UNTRUSTED_ROOT
```

But:

```powershell
curl.exe -k https://api.acrfp.site/health
# {"status":"ok","service":"api"}
```

**Meaning:** App + Ingress OK; certificate was **Let's Encrypt staging** (untrusted by design).  
**Fix:** Switch Ingress annotation to `letsencrypt-prod`, delete old cert/secret, re-apply:

```powershell
kubectl delete certificate acrfp-api-tls
kubectl delete secret acrfp-api-tls --ignore-not-found
kubectl apply -f infra\k8s\ingress\api-ingress.yaml
kubectl get certificate acrfp-api-tls -w
# Wait READY True
curl.exe https://api.acrfp.site/health
# {"status":"ok","service":"api"}  (no -k)
```

### 5) Stale pods after AKS restart (`ContainerStatusUnknown` / `Completed`, AGE 18d)

**Symptom:** Mix of new Running pods and old broken pods.  
**Meaning:** Leftovers from before stop; new pods are the real ones.  
**Optional cleanup:**

```powershell
kubectl delete pod <old-pod-name>
```

### 6) AKS cost while idle

**Fix when pausing work:**

```powershell
az aks stop --resource-group acrfp-rg --name acrfp-aks
```

**Resume later:**

```powershell
az aks start --resource-group acrfp-rg --name acrfp-aks
az aks get-credentials -g acrfp-rg -n acrfp-aks --overwrite-existing
```

Note: Stopping AKS pauses **node** cost; ACR + public IPs may still charge a little until full destroy.

---

## End-to-end UI test (live AKS) — customer demo script

Use the **public** site (not port-forward) so you prove the real customer path.

### Prerequisites

- AKS `Running`
- https://api.acrfp.site/health returns OK without `-k`

### Step 1 — Open the product

1. https://api.acrfp.site/health → `{"status":"ok","service":"api"}`  
2. https://api.acrfp.site/docs → Swagger  
3. https://api.acrfp.site/ui → Approval Console  

### Step 2 — Ingest sample incidents (from your PC)

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\ingest_samples.py https://api.acrfp.site
```

**Expected pattern (typical):**

| Sample title | Typical status | Why |
|--------------|----------------|-----|
| payments-api restart storm | `resolved` | Low risk → auto dry-run |
| checkout latency + spend spike | `resolved` | Often auto path |
| Idle VM spend anomaly | `awaiting_approval` | Medium → human gate |
| coredns in protected namespace | `awaiting_approval` | High → **2 approvers** |

### Step 3 — Refresh Approval UI

On https://api.acrfp.site/ui :

1. Click **Refresh** (or reload page)  
2. You should see pending approvals for Idle VM and/or coredns  

### Step 4 — Approve medium risk (Idle VM)

1. Set approver name to `alice`  
2. Click **Approve** on Idle VM  
3. Status should move toward resolved / executed (dry-run message in case/audit)

### Step 5 — Dual approve high risk (coredns)

1. Approve as `alice` → still pending (needs 2)  
2. Change name to `bob` → Approve again  
3. Same person twice should be **rejected** by dual-control rules  

### Step 6 — Verify audit trail

In Swagger https://api.acrfp.site/docs :

1. `GET /v1/incidents` → see all cases  
2. `GET /v1/approvals/pending` → should shrink after approvals  
3. `GET /v1/audit` → events like `incident.ingested`, `guardrail.verdict`, `approval.*`, `execution.result`  
4. Optional: `GET /v1/audit/export?format=csv`

### Step 7 — Pass criteria (demo checklist)

- [ ] Public HTTPS padlock trusted  
- [ ] Health OK  
- [ ] Ingest creates mixed auto + approval outcomes  
- [ ] `/ui` shows pending items  
- [ ] Medium approval works with 1 person  
- [ ] High risk needs 2 different approvers  
- [ ] Audit shows full trail  
- [ ] Executor stays dry-run (safe for demos)

---

## Key URLs (production path)

| Purpose | URL |
|---------|-----|
| Health | https://api.acrfp.site/health |
| Approval UI | https://api.acrfp.site/ui |
| Swagger | https://api.acrfp.site/docs |
| Ingress IP (DNS target) | Confirm live: `kubectl get svc -n ingress-nginx` (recreate showed `20.219.215.219`) |

---

## Next after platform (Helm app path — preferred)

Platform is ready when nginx/cert-manager/argocd pods are Running and Ingress has an EXTERNAL-IP.

```powershell
# 1) Point DNS at NEW ingress IP if it changed
kubectl get svc -n ingress-nginx ingress-nginx-controller

# 2) Build app image into ACR
az acr build -r acrfp752f8b6b -t acrfp-api:dev .

# 3) Deploy ACRFP with Helm (not week3 script)
helm upgrade --install acrfp infra/helm/acrfp -f infra/helm/acrfp/values-ingress.yaml

# 4) Wait for pods + cert
kubectl get pods
kubectl get ingress
kubectl get certificate

# 5) Customer test
curl.exe https://api.acrfp.site/health
```

Optional older path: `scripts/week3_aks_deploy.ps1` (kubectl manifests). Prefer Helm for interviews.

### Distroless image (security + size)

**Concept:** runtime image has **no shell, no apt, no package manager** — only app + minimal OS libs (Google Distroless).

| Before | After |
|--------|-------|
| `python:3.12-slim` single stage (~369MB) | Multi-stage → `gcr.io/distroless/python3-debian12:nonroot` (~252MB) |

- Builder stage installs deps; final stage copies only what is needed.
- No `bash`/`sh` in the running container → harder for attackers.
- Start process with `python3 -m uvicorn ...` (no shell form).
- Prod deps: `requirements-prod.txt` (no pytest).

Rebuild/push:

```powershell
docker build -t acrfp752f8b6b.azurecr.io/acrfp-api:dev .
docker push acrfp752f8b6b.azurecr.io/acrfp-api:dev
```

---

## Important file map

| Path | Role |
|------|------|
| `src/api/app.py` | API + approvals + `/ui` |
| `src/orchestrator/graph.py` | LangGraph flow |
| `src/guardrail/policy.py` | Allow / approve / deny |
| `src/executor/app.py` | Dry-run actions |
| `infra/terraform/` + `modules/rg` + `modules/aks` | RG + AKS (Terraform modules) |
| `infra/helm/acrfp/` | App Helm chart |
| `infra/helm/acrfp/values-ingress.yaml` | Public host `api.acrfp.site` + TLS |
| `infra/k8s/` | Optional kubectl manifests |
| `infra/k8s/ingress/api-ingress.yaml` | Raw Ingress + TLS issuer |
| `scripts/install_aks_platform.ps1` | Helm: nginx, cert-manager, Argo CD |
| `scripts/week3_aks_deploy.ps1` | Optional ACR build + kubectl apply |
| `scripts/ingest_samples.py` | Demo ingest |

---

## Phase 3 preview — Azure Foundry (not done yet)

**Goal:** set `LLM_PROVIDER=azure_foundry` so agents use a real model.  
**Guardrail still decides risk** — Foundry does not auto-approve dangerous actions.

When ready: create Foundry deployment → put endpoint/key in Secrets/env → restart API pods with new env → re-ingest and compare mock vs Foundry quality.

---

## Interview evidence (AKS stopped / offline)

When the cluster is stopped for cost, show interviewers the offline pack instead of a live demo:

| File | Use |
|------|-----|
| [`docs/interview-evidence/INTERVIEW_DEMO.html`](interview-evidence/INTERVIEW_DEMO.html) | Screen-share walkthrough + screenshots |
| [`docs/interview-evidence/README.md`](interview-evidence/README.md) | Speaking outline + capture steps |

Refresh screenshots while AKS is still up:

```powershell
.\scripts\capture_interview_evidence.ps1
```

Then stop the cluster.

---

## Cost hygiene

After demos today:

```powershell
az aks stop --resource-group acrfp-rg --name acrfp-aks
```

Full teardown (near-zero cost, recreate later with Terraform):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\terraform_destroy.ps1
```
