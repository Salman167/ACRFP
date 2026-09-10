# ACRFP — Local Working Commands (Reference)

Last verified: **API `8010`** + **Executor `8002`** + **Approval UI `/ui`** + **Week 3 Azure prep**.

> **Maintainer rule:** whenever a new feature is added, update this file **and** architecture notes/images (`docs/images/`, README architecture section).

> PowerShell note: if `Activate.ps1` or any `scripts\*.ps1` is blocked, **do not change system policy**.  
> Run scripts with bypass, or call tools directly:
> ```powershell
> powershell -ExecutionPolicy Bypass -File powershell -ExecutionPolicy Bypass -File .\scripts\week3_aks_deploy.ps1
> powershell -ExecutionPolicy Bypass -File powershell -ExecutionPolicy Bypass -File .\scripts\terraform_apply.ps1
> ```
> For Python venv, use `.venv\Scripts\python.exe` directly (no `Activate.ps1`).

---

## Architecture docs + images

Full write-up: **`docs/architecture.md`** (embeds both images).

| Image | Path |
|-------|------|
| Full platform architecture | `docs/images/acrfp-architecture.png` |
| Frontend vs Backend | `docs/images/acrfp-frontend-backend.png` |

Also shown in README **Architecture** section. Use for LinkedIn and demo video intro.

---

## What each terminal is for

| Terminal | Service / role | Port | Keep open? |
|----------|----------------|------|------------|
| **A** | **API** (front door + agents + guardrail + audit + `/ui`) | `8010` | Yes |
| **B** | **Executor** (dry-run kubectl/Azure actions) | `8002` | Yes |
| **C** | **Ingest script** (sends sample incidents) | — | No (run once) |

If Terminal B says port already in use (`10048`), Executor is **already running** — skip B and continue.

---

## Terminal A — start API

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:PYTHONPATH = "src"
$env:LLM_PROVIDER = "mock"
$env:POLICY_PACK = "local"
$env:EXECUTOR_URL = "http://127.0.0.1:8002"
.\.venv\Scripts\python.exe -m uvicorn api.app:app --reload --host 127.0.0.1 --port 8010
```

**Check:** http://127.0.0.1:8010/health  
**Swagger:** http://127.0.0.1:8010/docs  
**Approval UI:** http://127.0.0.1:8010/ui  

---

## Terminal B — start Executor

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:PYTHONPATH = "src"
$env:ACRFP_MODE = "local"
.\.venv\Scripts\python.exe -m uvicorn executor.app:app --host 127.0.0.1 --port 8002
```

**Check:** http://127.0.0.1:8002/health  
Expected: `{"status":"ok","service":"executor"}`

---

## Terminal C — ingest sample incidents

Run only after A and B are healthy:

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\ingest_samples.py http://127.0.0.1:8010
```

**Expected output (4 samples):**
- `payments-api restart storm` → auto low-risk / resolved
- `Idle VM spend anomaly` → `awaiting_approval` (Approve in UI as `alice`)
- `checkout latency + spend spike` → auto scale dry-run / resolved
- `coredns restart in protected namespace` → `awaiting_approval` with **need=2** (dual approval: `alice` then `bob`)

---

## What does “re-ingest” mean? (important)

**Ingest** = send sample incident JSON into the API  
(`scripts\ingest_samples.py` → `POST /v1/incidents/ingest`)

**Re-ingest** = run that ingest script **again**.

### Why you need it
- Incidents are stored **in memory** in the API process.
- If you **restart the API**, the list goes back to **0**.
- If we **add new sample events** (like coredns dual-approval), old data in memory does not auto-update.
- So you run the ingest script again to create **fresh** incidents.

### What you need first
1. **API must be running** (Terminal A on port `8010`)  
   - If API is stopped, ingest fails / connection refused.
2. Prefer **Executor running** too (Terminal B on `8002`)  
   - So auto-allow paths can dry-run successfully.
3. Then run Terminal C ingest command.

### Simple analogy
- API = empty notebook when it starts  
- Ingest = write new incident pages into the notebook  
- Re-ingest = write those pages again (or add the new ones)

---

## Approval UI — how to use + how to verify it worked

### Use
1. Ingest samples (Terminal C)
2. Open http://127.0.0.1:8010/ui
3. Set approver name (`alice`)
4. Click **Approve** on pending item(s)
5. For dual-approval (coredns): approve as `alice`, change name to `bob`, approve again

### Verify after Approve (your Idle VM case already worked)
Open these and confirm:

| Check | URL / place | Good result |
|-------|-------------|-------------|
| Pending empty (or fewer) | `/ui` or `/v1/approvals/pending` | Idle VM gone from pending |
| Incident resolved | `/ui` Recent incidents or `/v1/incidents` | Idle VM status = `resolved` |
| Audit has approval | `/v1/audit` or Swagger | `approval.decision` … `approved by alice` |
| Audit has dry-run | `/v1/audit` | `execution.result` with `DRY-RUN: az vm deallocate...` and `success: true` |

Example success lines you already saw:
- `approval.decision | approved by alice ...`
- `execution.result | DRY-RUN: az vm deallocate ...`

---

## Swagger UI checklist (what to click)

Open: **http://127.0.0.1:8010/docs**

Important: after each endpoint, look at **Response body** (real data),  
not **Example Value / Schema** (placeholders like `"string"`).

### 1) `GET /v1/incidents`
- Try it out → Execute  
- Confirm **3 incidents**

### 2) `GET /v1/approvals/pending`
- Try it out → Execute  
- Copy `approval_id` (example: `apr_...`)  
- This is usually the **Idle VM** case

### 3) `POST /v1/approvals/{approval_id}/decide`
- Try it out  
- Paste `approval_id`  
- Request body:

```json
{
  "decision": "approved",
  "decided_by": "alice"
}
```

- Execute  
- For **HIGH** risk later: approve again with a different person, e.g. `"bob"` (dual approval)

### 4) `GET /v1/audit`
- Try it out → Execute  
- Good signs:
  - `incident.ingested`
  - `guardrail.verdict` (`allow` or `require_approval`)
  - `approval.decision` (after you approve)
  - `execution.result` with **`DRY-RUN: kubectl ...`** and `"success": true`

### 5) `GET /v1/audit/export?format=csv`
- Downloads / returns CSV audit for demos / interviews

---

## What a successful auto path looks like (audit)

Example you already saw (checkout):

1. `incident.ingested` → checkout latency + spend spike  
2. `guardrail.verdict` → `allow` / `low` / `scale_deployment`  
3. `execution.result` → `DRY-RUN: kubectl scale deployment/checkout-svc ...` / `success: true`

That means: **API + Guardrail + Executor** all worked.

---

## Common errors and fixes

| Error | Meaning | Fix |
|-------|---------|-----|
| `Activate.ps1` or `scripts\*.ps1` blocked | PowerShell execution policy | Use `powershell -ExecutionPolicy Bypass -File .\scripts\...` or `.venv\Scripts\python.exe` |
| `WinError 10013` on 8000 | Port busy/blocked | Use `--port 8010` |
| Browser `ERR_CONNECTION_REFUSED` on 8002 | Executor not running | Start Terminal B |
| Audit: `executor unreachable` | API cannot reach Executor | Start Executor; set `EXECUTOR_URL=http://127.0.0.1:8002`; re-ingest |
| Ingest title = `"string"` | Swagger placeholder body | Prefer `scripts\ingest_samples.py` |

---

## Optional: run tests

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:PYTHONPATH = "src"
$env:LLM_PROVIDER = "mock"
$env:POLICY_PACK = "local"
.\.venv\Scripts\python.exe -m pytest -q
```

---

## Optional: Docker full stack

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
docker compose up --build
```

(Uses compose ports; see `docker-compose.yml`.)

---

## Done vs pending

### Done (local / Week 1 + Phase A)
- Multi-agent flow (Diagnosis, Cost, Remediation)
- LangGraph orchestrator
- Guardrail + YAML policy packs (`local` / `prod`)
- Dual approval for HIGH risk
- Audit trail + export
- Local API + Executor dry-run
- Sample ingest demo via 3 terminals + Swagger
- Tests / Docker / K8s manifests / CI skeleton
- Approval web UI (`/ui`)
- Region lock + webhook notify + dual approval samples
- **Terraform modules** (`modules/rg` + `modules/aks`) — live cluster in `centralindia`
- Architecture doc: `docs/architecture.md` + images
- **App deployed to AKS** — image in ACR, pods Running (`week3_aks_deploy.ps1 -BuildMethod local`)
- **Platform on AKS** — Helm, nginx-ingress, cert-manager, Argo CD (`install_aks_platform.ps1`)
- **Ingress + TLS** configured for `api.acrfp.site` (cert pending until GoDaddy DNS)

### Pending (next)
- **GoDaddy DNS** — A record `api` → `20.207.74.242` (required for HTTPS cert)
- Switch issuer from `letsencrypt-staging` → `letsencrypt-prod` after DNS works
- Real Azure wiring:
  - Event Hubs / Service Bus
  - Azure AI Search (RAG)
  - Cost Management APIs
  - Microsoft Foundry LLM
  - Key Vault + Monitor
  - Live executor (still behind guardrail)
- Demo video + CV bullets

---

## Week 2 roadmap (why + how) — start here

### Step 1 — Approval web UI ✅ (added)
- **Why:** Interviewers/recruiters prefer a clickable console over raw Swagger.
- **How:** Browser page calls the same approval APIs.
- **Open:** http://127.0.0.1:8010/ui

### Step 2 — Sovereign region lock ✅ (added)
- **Why:** EU/Gulf story — only act in allowed regions (e.g. `westeurope`, `uaenorth`).
- **How:** Policy YAML `allowed_regions`; guardrail denies others (`POL-REGION-LOCK-001`).

### Step 3 — More sample events ✅
- Added 4th sample: **coredns in kube-system** → HIGH + dual approval (`alice` + `bob`)

### Step 4 — Webhook notify ✅
- Set `NOTIFY_WEBHOOK_URL` in `.env` to a Teams/Slack incoming webhook
- On pending approval, API POSTs a JSON payload (no-op if empty)

### Step 5 — Azure account prep ✅ (Week 3 started)
- Azure CLI installed and logged in on this PC
- **Infra = Terraform only** (`infra/terraform/`) — RG + AKS in `centralindia`

### After Week 2 → Azure weeks (brief)
| Week | What | Why |
|------|------|-----|
| 3 | Terraform RG + AKS + app deploy | Host platform on Azure |
| 4 | Event Hubs | Real alert ingest pipe |
| 5 | AI Search | Real vector RAG for runbooks |
| 6 | Cost APIs + Foundry LLM | Real FinOps + real model |
| 7 | Key Vault + live executor | Secrets + real actions behind guardrail |
| 8 | Demo polish | Job-ready packaging |

---

## Week 3 — Azure infra (Terraform only — single path)

> **Rule:** AKS + Resource Group are created **only** with Terraform (`infra/terraform/`).  
> App deploy to AKS still uses `scripts/week3_aks_deploy.ps1` (ACR build + kubectl).

See also: **`docs/architecture.md`** (platform + Azure layout + images).

### Architecture (Week 3)

```text
Terraform (modules)              App deploy script
───────────────────              ─────────────────
module.rg  → acrfp-rg            az acr build → push image
module.aks → acrfp-aks (B2s_v2) → kubectl apply → api + guardrail + executor
```

| Module | Path | Creates |
|--------|------|---------|
| `rg` | `infra/terraform/modules/rg` | Resource group |
| `aks` | `infra/terraform/modules/aks` | AKS cluster |

Root `main.tf` only wires modules + outputs (kept simple).

### Step W3-1 — Azure CLI ✅ + login ✅
Already done on this PC.

### Step W3-2 — Remove old script-created AKS (one-time cleanup)

> **Status on this PC:** ✅ Done — `acrfp-rg-in` and old westeurope `acrfp-rg` removed.

**Why:** Old cluster was created with `az aks create`. We switch to Terraform-only.

```powershell
$env:Path = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;" + $env:Path
az group delete --name acrfp-rg-in --yes --no-wait
az group delete --name acrfp-rg --yes --no-wait
```

Wait ~2–5 min, then check portal: no `acrfp-rg-in`, no old `acrfp-rg`.

**Why delete both:** `acrfp-rg-in` had script AKS; old `acrfp-rg` was westeurope empty — Terraform recreates `acrfp-rg` in **centralindia**.

### Step W3-3 — Install Terraform ✅

> **Status on this PC:** ✅ Terraform **1.15.8** installed via winget.

```powershell
winget install -e --id Hashicorp.Terraform
```

Close PowerShell, open new window: `terraform version`

Register AKS provider (once per subscription):
```powershell
az provider register --namespace Microsoft.ContainerService --wait
```

### Step W3-4 — Create AKS with Terraform ✅

> **Status on this PC:** ✅ `acrfp-rg` + `acrfp-aks` in **centralindia** (Terraform-managed).

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:Path = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;" + $env:Path
powershell -ExecutionPolicy Bypass -File .\scripts\terraform_apply.ps1
```

Or manually:
```powershell
cd infra\terraform
terraform init
terraform plan
terraform apply
```

**Terraform creates:**

| Resource | Value |
|----------|--------|
| Resource group | `acrfp-rg` |
| Region | `centralindia` |
| AKS | `acrfp-aks` |
| Node VM | `Standard_B2s_v2` × 1 |

Config file: `infra/terraform/terraform.tfvars`

### Step W3-5 — Get kubectl access ✅

> **Status on this PC:** ✅ Node `aks-nodepool1-...` Ready.

```powershell
az aks get-credentials --resource-group acrfp-rg --name acrfp-aks --overwrite-existing
kubectl get nodes
```

### Step W3-6 — Deploy app to AKS ✅

> **Status on this PC:** ✅ Done — image in ACR, 4 pods Running on `acrfp-aks`.

**Free/trial Azure blocks `az acr build` (ACR Tasks).** Use local Docker instead:

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
# Make sure Docker Desktop is running first
powershell -ExecutionPolicy Bypass -File .\scripts\week3_aks_deploy.ps1 -BuildMethod local
```

Or auto (tries cloud, falls back to Docker):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\week3_aks_deploy.ps1 -BuildMethod auto
```

### Step W3-7 — Test on AKS

**Terminal 1:**
```powershell
kubectl port-forward svc/acrfp-api 8010:80
```

**Terminal 2:**
```powershell
# http://127.0.0.1:8010/ui
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\ingest_samples.py http://127.0.0.1:8010
```

### Step W3-8 — Pause AKS (stop billing for nodes, keep cluster for later)

> **Status on this PC:** ✅ `acrfp-aks` **Stopped** (2026-07-21) — restart when you resume the project.

```powershell
# Stop AKS (nodes off — main cost stops; cluster config kept)
az aks stop --resource-group acrfp-rg --name acrfp-aks

# Later — start again (5–10 min), then re-check pods / ingress
az aks start --resource-group acrfp-rg --name acrfp-aks
az aks get-credentials --resource-group acrfp-rg --name acrfp-aks --overwrite-existing
kubectl get nodes
kubectl get pods -A
```

**Do NOT delete** `MC_acrfp-rg_acrfp-aks_centralindia` by hand — Azure manages it with AKS.

### Step W3-9 — FULL DELETE (Terraform destroy — only if you never need this cluster)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\terraform_destroy.ps1
```

Or: `cd infra\terraform && terraform destroy`

**Why:** Removes RG + AKS completely. Use when you want near-zero Azure cost (not just pause).

---

## AKS full infra explained (how we know you are "live on AKS")

### What "live on AKS" means

Your app is **not** running on your laptop anymore for the deployed path. It is running **inside Kubernetes pods on an Azure VM** in the `acrfp-aks` cluster.

**Proof (run these yourself):**

```powershell
kubectl get pods
kubectl get svc
kubectl get deploy
az acr repository list --name acrfp752f8b6b -o table
```

You are live when ALL of these are true:

| Check | Command | What you should see |
|-------|---------|---------------------|
| Pods Running | `kubectl get pods` | `acrfp-api`, `acrfp-guardrail` (x2), `acrfp-executor` all `1/1 Running` |
| Deployments ready | `kubectl get deploy` | `READY` column matches desired (e.g. `1/1`, `2/2`) |
| Image from ACR | `kubectl get deploy -o wide` | `IMAGE` = `acrfp752f8b6b.azurecr.io/acrfp-api:dev` |
| Image in registry | `az acr repository list --name acrfp752f8b6b` | `acrfp-api` listed |
| Health responds | port-forward + `/health` | `{"status":"ok"}` from the cluster |

**"Live" does NOT mean** you have a public URL yet. Services are `ClusterIP` (internal only). You reach the app via `kubectl port-forward` or by switching to `LoadBalancer`.

---

### The full stack (bottom to top)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  YOUR PC                                                                │
│  ┌──────────────┐    port-forward     ┌─────────────────────────────┐ │
│  │ Browser /ui  │ ◄────────────────── │ kubectl → acrfp-api service   │ │
│  │ ingest script│                     └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  AZURE — Resource Group: acrfp-rg (centralindia)                        │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  AKS cluster: acrfp-aks                                          │  │
│  │  Node VM: Standard_B2s_v2 × 1 (aks-nodepool1-...)                │  │
│  │                                                                  │  │
│  │  Pod: acrfp-api         ──► Service acrfp-api:80                 │  │
│  │  Pod: acrfp-guardrail×2 ──► Service acrfp-guardrail:8001         │  │
│  │  Pod: acrfp-executor    ──► Service acrfp-executor:8002         │  │
│  │                                                                  │  │
│  │  All 3 deployments use SAME Docker image, different commands:    │  │
│  │    api: default CMD    guardrail: uvicorn guardrail.app          │  │
│  │    executor: uvicorn executor.app                                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    ▲ pulls image                        │
│  ┌─────────────────────────────────┴────────────────────────────────┐  │
│  │  ACR: acrfp752f8b6b.azurecr.io                                   │  │
│  │  Image: acrfp-api:dev                                            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Layer 1 — Terraform creates the "empty hotel" (infra only)

**Tool:** `scripts/terraform_apply.ps1` → `infra/terraform/`

| Resource | Name | What it is |
|----------|------|------------|
| Resource Group | `acrfp-rg` | Folder in Azure that holds everything |
| AKS cluster | `acrfp-aks` | Managed Kubernetes control plane + nodes |
| Node pool | `nodepool1` | 1× VM `Standard_B2s_v2`, 30 GB disk, `centralindia` |

Terraform does **NOT** deploy your Python app. It only creates the cluster (empty rooms). No Docker image, no pods.

**Files:**
- `infra/terraform/main.tf` — wires `module.rg` + `module.aks`
- `infra/terraform/modules/rg/main.tf` — resource group
- `infra/terraform/modules/aks/main.tf` — AKS cluster definition
- `infra/terraform/terraform.tfvars` — your settings (`prefix`, `location`, `vm_size`)

---

### Layer 2 — Docker image = packaged app (recipe → box)

**Tool:** `Dockerfile` at repo root

```dockerfile
FROM python:3.12-slim          # base OS + Python
COPY requirements.txt .        # install deps
RUN pip install ...
COPY src ./src                 # your Python code
COPY data ./data               # runbooks, policies, samples
CMD uvicorn api.app:app ...    # default: run API on port 8000
```

**What Docker does:** Takes your source code and bakes it into a **read-only image** (like a snapshot). That image can run anywhere Docker/Kubernetes supports.

**One image, three roles on AKS:** Same image `acrfp-api:dev` runs as API, Guardrail, or Executor — K8s overrides the start command in `infra/k8s/guardrail.yaml` and `executor.yaml`.

---

### Layer 3 — ACR = image warehouse in Azure

**Tool:** `scripts/week3_aks_deploy.ps1` (build + push step)

| Item | Value |
|------|-------|
| Registry name | `acrfp752f8b6b` |
| Login server | `acrfp752f8b6b.azurecr.io` |
| Image tag | `acrfp-api:dev` |
| Full image URL | `acrfp752f8b6b.azurecr.io/acrfp-api:dev` |

**Two ways to get the image into ACR:**

| Method | Command | Works on free trial? |
|--------|---------|----------------------|
| Cloud build | `az acr build` | **No** — `TasksOperationsNotAllowed` |
| Local build + push | `docker build` + `docker push` | **Yes** — use `-BuildMethod local` |

**Deploy script flow:**
1. `az acr show` — registry exists? (creates if missing)
2. Build image (cloud or local Docker)
3. `az aks update --attach-acr` — lets AKS pull from your private registry
4. Render `infra/k8s/*.yaml` → `infra/k8s-rendered/` (swap placeholder image URL)
5. `kubectl apply -f infra/k8s-rendered` — create pods + services

---

### Layer 4 — Kubernetes manifests = "run this image like this"

**Source templates:** `infra/k8s/`

| File | Creates | Replicas | Port |
|------|---------|----------|------|
| `api.yaml` | Deployment + Service `acrfp-api` | 1 | 80 → 8000 |
| `guardrail.yaml` | Deployment + Service `acrfp-guardrail` | 2 | 8001 |
| `executor.yaml` | Deployment + Service + ServiceAccount | 1 | 8002 |

**Key env vars inside API pod:**
- `GUARDRAIL_URL=http://acrfp-guardrail:8001` — in-cluster DNS name
- `EXECUTOR_URL=http://acrfp-executor:8002`
- `LLM_PROVIDER=mock` — no API keys needed for demo

Pods talk to each other **inside the cluster** using service names, not `localhost`.

---

### Layer 5 — How traffic reaches you

AKS services are `ClusterIP` (private). To test from your PC:

```powershell
# Terminal 1 — tunnel from your laptop into the cluster
kubectl port-forward svc/acrfp-api 8010:80

# Terminal 2 — send sample incidents into the cluster
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\ingest_samples.py http://127.0.0.1:8010
```

Browser: http://127.0.0.1:8010/ui

`port-forward` is a temporary pipe: your PC port 8010 → cluster service `acrfp-api` port 80 → pod port 8000.

---

### Local vs AKS — same app, different host

| | Local (your PC) | AKS (Azure) |
|--|-----------------|-------------|
| API | `uvicorn` on port 8010 | Pod in cluster |
| Guardrail | separate terminal or docker-compose | Pod `acrfp-guardrail` |
| Executor | separate terminal or docker-compose | Pod `acrfp-executor` |
| Data store | in-memory (resets on restart) | in-memory (resets on pod restart) |
| Reach UI | http://127.0.0.1:8010/ui | port-forward same URL |

---

### Verify you are live (copy-paste checklist)

```powershell
# 1) Cluster credentials
az aks get-credentials --resource-group acrfp-rg --name acrfp-aks --overwrite-existing

# 2) Nodes ready
kubectl get nodes
# expect: STATUS Ready

# 3) All app pods running
kubectl get pods
# expect: acrfp-api, acrfp-executor, acrfp-guardrail x2 = Running

# 4) Image came from your ACR
kubectl get deploy acrfp-api -o jsonpath="{.spec.template.spec.containers[0].image}"
# expect: acrfp752f8b6b.azurecr.io/acrfp-api:dev

# 5) Health check through tunnel
# (start port-forward in another terminal first)
curl http://127.0.0.1:8010/health
# expect: {"status":"ok",...}
```

---

## AKS deploy + test — end to end (why each step)

```text
Your code (Multi_agents/)
        │
        ▼
  docker build (local) OR az acr build (cloud — blocked on free trial)
        │
        ▼
  docker push → Azure Container Registry (acrfp752f8b6b.azurecr.io/acrfp-api:dev)
        │
        ▼
  az aks update --attach-acr  (AKS allowed to pull private image)
        │
        ▼
  kubectl apply  (create Deployments + Services from infra/k8s-rendered/)
        │
        ▼
  AKS pulls image → starts pods on node VM
        │
        ▼
  kubectl port-forward → http://127.0.0.1:8010/ui → ingest → approve → audit
```

| Step | Tool | Why |
|------|------|-----|
| Infra (RG + AKS) | **Terraform only** | Single IaC path, interview story |
| App image | `docker build` + `docker push` (free trial) or `az acr build` (paid) | Package app for Kubernetes |
| Registry | ACR `acrfp752f8b6b` | Private image store in same region |
| App pods | `kubectl apply` | Run same app as local, on Azure VM |
| Test | `port-forward` | Free vs LoadBalancer public IP |

### Delete when finished (stop credits)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\terraform_destroy.ps1
```

---

## Week 3.5 — DNS + HTTPS + Argo CD (domain: acrfp.site)

> **Domain:** `acrfp.site` bought on **GoDaddy**  
> **App hostname:** `api.acrfp.site`  
> **nginx LoadBalancer IP:** run `kubectl get svc -n ingress-nginx ingress-nginx-controller` (currently `20.207.74.242`)  
> **Argo CD LB IP (optional):** `kubectl get svc -n argocd argocd-server`

### Do you need DNS on a website?

**Yes.** You already bought the domain on GoDaddy — that is the right place. You do **not** need another registrar. You only add **DNS records** inside GoDaddy so `api.acrfp.site` points to your Azure nginx LoadBalancer IP.

| Record | Type | Name | Value | TTL |
|--------|------|------|-------|-----|
| App API | **A** | `api` | nginx LB IP (e.g. `20.207.74.242`) | 600 sec |
| Argo CD (optional) | **A** | `argocd` | Argo CD LB IP (e.g. `4.247.233.155`) | 600 sec |

**GoDaddy steps (do this once):**

1. Sign in at [godaddy.com](https://www.godaddy.com) → **My Products**
2. Click **DNS** next to **acrfp.site**
3. **Add** → Type **A**, Name **`api`**, Value **`20.207.74.242`**, TTL **600** → Save
4. (Optional) Add **A** record Name **`argocd`**, Value **Argo CD external IP**
5. Wait 5–30 minutes for DNS propagation

**Verify DNS from your PC:**

```powershell
nslookup api.acrfp.site
# expect: Address = 20.207.74.242
```

### Step W3.5-1 — Install platform (Helm + nginx + cert-manager + Argo CD) ✅

> **Status on this PC:** ✅ Done

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
powershell -ExecutionPolicy Bypass -File .\scripts\install_aks_platform.ps1 -LetsEncryptEmail admin@acrfp.site
```

Installs (if missing): **Helm**, **nginx-ingress**, **cert-manager**, **Argo CD**, Let's Encrypt ClusterIssuers.

### Step W3.5-2 — Deploy app with Ingress + TLS

**If app was deployed with `week3_aks_deploy.ps1` (kubectl), apply Ingress directly:**

```powershell
kubectl apply -f infra/k8s/ingress/api-ingress.yaml
kubectl get ingress
kubectl get certificate
```

**Or use Helm on a fresh cluster** (not after kubectl apply — Helm cannot adopt existing resources):

```powershell
helm upgrade --install acrfp infra/helm/acrfp -f infra/helm/acrfp/values-ingress.yaml
```

After GoDaddy A record for `api` is live:

**When staging works**, edit `infra/helm/acrfp/values-ingress.yaml`:

```yaml
clusterIssuer: letsencrypt-prod
```

Then redeploy:

```powershell
helm upgrade --install acrfp infra/helm/acrfp -f infra/helm/acrfp/values-ingress.yaml
```

### Step W3.5-3 — Test HTTPS app

```powershell
curl https://api.acrfp.site/health
# expect: {"status":"ok","service":"api"}

# Browser:
#   https://api.acrfp.site/ui
#   https://api.acrfp.site/docs

# Ingest against live URL:
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\ingest_samples.py https://api.acrfp.site
```

> **Staging cert:** Browser may warn “not secure” with `letsencrypt-staging` — that is normal. Switch to `letsencrypt-prod` for a trusted cert.

### Step W3.5-4 — Argo CD (GitOps)

**Get admin password (run locally — do not share):**

```powershell
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
```

**Open UI:** `https://<argocd-external-ip>` or port-forward:

```powershell
kubectl port-forward svc/argocd-server -n argocd 8080:443
# https://localhost:8080  user: admin
```

**Register app** (after pushing repo to GitHub and editing `repoURL` in `infra/argocd/acrfp-application.yaml`):

```powershell
kubectl apply -f infra/argocd/acrfp-application.yaml
```

### Architecture (ingress + DNS)

See **`docs/architecture.md`** — mermaid diagram: GoDaddy DNS → nginx → Ingress TLS → acrfp-api → guardrail / executor.

```text
Internet
   │
   ▼
GoDaddy: api.acrfp.site  (A record)
   │
   ▼
nginx LoadBalancer (20.207.74.242)
   │  TLS via cert-manager + Let's Encrypt
   ▼
Ingress api.acrfp.site
   ▼
acrfp-api (ClusterIP) ──► guardrail, executor (internal)
```

### Troubleshooting HTTPS

| Problem | Check | Fix |
|---------|-------|-----|
| `nslookup` wrong IP | GoDaddy DNS | Fix A record; wait propagation |
| Certificate `Pending` | `kubectl describe certificate acrfp-api-tls` | DNS must resolve to nginx IP first |
| Connection timeout on port 80 | `Test-NetConnection api.acrfp.site -Port 80` | Add Azure LB health probe annotation (see below) |
| NSG rules not helping | Portal → inbound rules | **Source port** must be `*`, not `80`; dest port `80`/`443` |
| 404 from nginx | `kubectl get ingress` | Host must be `api.acrfp.site` |
| cert-manager issuer not ready | `kubectl get clusterissuer` | Re-run platform install with real email |
| Browser "not secure" with staging | `values-ingress.yaml` / ingress yaml | Switch `clusterIssuer` to `letsencrypt-prod` and re-apply |

**AKS + nginx fix (connection timeout even with correct NSG):**

```powershell
helm upgrade ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --reuse-values `
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz
```

Then retry cert: delete ingress + re-apply `infra/k8s/ingress/api-ingress.yaml`.

---

## Demo video — 3-minute recording script (do this later)

You record on your PC (Win + G / OBS). Cursor cannot record your screen.

### Before you press Record

1. Close extra windows; keep desktop clean.
2. Start **Terminal A (API 8010)** and **Terminal B (Executor 8002)** using commands above.
3. Confirm:
   - http://127.0.0.1:8010/health
   - http://127.0.0.1:8002/health
4. Open browser tab: http://127.0.0.1:8010/docs (zoom ~125%).
5. Optional first slide: architecture image under project assets / README diagram.
6. Mic on. Practice once without recording.

### How to start recording (Windows)

1. Press **Win + G** (Xbox Game Bar)
2. Click **Capture** → **Record** (or **Win + Alt + R**)
3. Follow the timed script below
4. Stop with **Win + Alt + R**
5. Video usually lands in: `Videos\Captures`

(Alternative: OBS Studio for higher quality.)

### Timed click script (~3–4 minutes)

| Time | What to show | What to say (approx) | Clicks / actions |
|------|----------------|----------------------|------------------|
| 0:00–0:25 | Face camera optional OR architecture / README title | “This is my Agentic Cloud Reliability & FinOps platform. Multi-agent system for Azure/Kubernetes ops with a guardrail and human approval.” | Show title briefly |
| 0:25–0:50 | Terminal A + Terminal B | “API on 8010 is the front door. Executor on 8002 dry-runs kubectl. Agents never bypass the guardrail.” | Scroll both terminals so ports are visible |
| 0:50–1:20 | Terminal C | “I ingest three sample incidents: restart storm, idle VM cost waste, and checkout latency spike.” | Run ingest command from this file |
| 1:20–1:50 | Swagger `GET /v1/incidents` | “Three cases opened. Low-risk reliability actions can auto-remediate.” | Try it out → Execute → scroll Response body |
| 1:50–2:20 | Swagger `GET /v1/approvals/pending` | “Idle VM is medium risk — FinOps action waits for a human. That is trusted autonomy.” | Execute → copy `approval_id` |
| 2:20–2:50 | Swagger `POST /v1/approvals/{id}/decide` | “I approve as alice. High-risk actions would need dual approval.” | Body: `{"decision":"approved","decided_by":"alice"}` → Execute |
| 2:50–3:30 | Swagger `GET /v1/audit` | “Full audit trail: ingested, guardrail verdict, approval, DRY-RUN kubectl. Important for EU and Gulf regulated clouds.” | Execute → highlight `DRY-RUN` + `success: true` |
| 3:30–4:00 | Brief glance at `src/guardrail/policy.py` OR README pending Azure list | “Policy is authoritative — the LLM cannot self-approve. Local demo today; Azure AKS, Event Hubs, Cost APIs, Foundry next.” | Stop recording |

### Spoken closing (memorize)

> “So the enterprise problem I solve is safe autonomy: faster recovery for low-risk 2 AM issues, FinOps savings for idle waste with human gates, and an audit trail for compliance. Same control plane later wires to Azure production.”

### After recording

1. Trim silence (Clipchamp / CapCut / Photos).
2. Export MP4, 1080p if possible.
3. Upload: YouTube **Unlisted** or Google Drive link.
4. Add link to README + CV / LinkedIn.
5. Suggested title: `ACRFP Demo — Guardrailed Multi-Agent Cloud Ops (Local)`

### Do / Don’t

- **Do** show Response body (real JSON), not Example Schema `"string"`.
- **Do** keep API + Executor running during the whole video.
- **Don’t** show secrets, personal email, or unrelated desktop files.
- **Don’t** claim live Azure production if you only show local dry-run — say “production-shaped local demo; Azure path is next.”
