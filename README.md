# Agentic Cloud Reliability & FinOps Platform (ACRFP)

Multi-agent system that watches Kubernetes/cloud signals, diagnoses **reliability** and **cost** issues, proposes typed fixes, and executes only what a **guardrail policy** allows — with a human approval gate for anything destructive.

Built for portfolio depth aimed at **EU public sector** and **Gulf (UAE/KSA) Azure/sovereign cloud** roles: agents that *manage infrastructure*, not just chat.

## Architecture

Full notes: [`docs/architecture.md`](docs/architecture.md)

![ACRFP architecture](docs/images/acrfp-architecture.png)

![Frontend vs Backend](docs/images/acrfp-frontend-backend.png)

```
Event (mock / Event Hubs)
        │
        ▼
   API Gateway ──► LangGraph Orchestrator
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
     Diagnosis     Cost/FinOps  Remediation
     (runbooks)    (cost APIs)  (structured proposals)
                      │
                      ▼
              Guardrail Proxy  ◄── authoritative risk policy
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
      ALLOW     REQUIRE_APPROVAL  DENY
         │            │
         ▼            ▼
     Executor     Human queue (/ui)
   (kubectl/ARM dry-run → live later)
```

**Non-negotiable separation (interview talking point):**
1. Agents never call `kubectl`/ARM directly.
2. Guardrail risk is computed from **action type + parameters**, not LLM self-rating.
3. Executor never runs without an allow/approval path.

## Repo layout

| Path | Role |
|------|------|
| `src/orchestrator/` | LangGraph state machine |
| `src/agents/` | Diagnosis, cost, remediation specialists |
| `src/guardrail/` | Policy engine + HTTP proxy |
| `src/executor/` | Dry-run / future live actions |
| `src/api/` | Ingest + incident + approval APIs |
| `data/runbooks/` | Local RAG corpus |
| `infra/k8s/` | AKS deploy manifests |
| `infra/helm/acrfp/` | Helm chart for AKS / GitOps deploys |
| `infra/argocd/` | Argo CD application manifest |
| `infra/terraform/` | Terraform root — calls `modules/rg` + `modules/aks` |
| `docs/architecture.md` | Architecture write-up + images |
| `docs/interview-evidence/` | Offline interviewer demo pack (HTML + screenshots) |
| `scripts/capture_interview_evidence.ps1` | Capture live screenshots/API dumps before stopping AKS |
| `scripts/terraform_apply.ps1` | Create Azure infra |
| `scripts/week3_aks_deploy.ps1` | Build image in ACR + kubectl apply |
| `tests/` | Guardrail, graph smoke, and golden-set evals |
| `data/evals/` | Golden incidents for the eval harness |
| `src/evals/` | Eval runner used by pytest, CLI, and `/v1/evals/run` |

## Quick start (local) — Command Prompt (`cmd.exe`)

Open **Command Prompt** (not PowerShell):

```bat
cd /d c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
set PYTHONPATH=src
set LLM_PROVIDER=mock
```

### Option A — run API only (in-process guardrail fallback)

```bat
uvicorn api.app:app --reload --port 8000
```

Open a **second** Command Prompt:

```bat
cd /d c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
.venv\Scripts\activate.bat
set PYTHONPATH=src
python scripts\ingest_samples.py
```

### Option B — full local stack (Docker)

```bat
copy .env.example .env
docker compose up --build
```

Then ingest (with venv activated + `PYTHONPATH=src` as above):

```bat
python scripts\ingest_samples.py
```

### Useful endpoints

- `GET  /health`
- `POST /v1/incidents/ingest`
- `GET  /v1/incidents`
- `GET  /v1/approvals/pending`
- `POST /v1/approvals/{id}/decide` body: `{"decision":"approved","decided_by":"you"}`

Interactive docs: http://localhost:8000/docs

### Tests

```bat
set PYTHONPATH=src
set LLM_PROVIDER=mock
pytest -q
```

### Golden-set evals

Scores the **pipeline** (routing, typed proposals, guardrail verdicts) against fixtures in `data/evals/golden_cases.yaml`. Same runner as CI.

```bat
set PYTHONPATH=src
set LLM_PROVIDER=mock
python scripts\run_evals.py
```

Or with the API running: `POST /v1/evals/run` · `GET /v1/evals` · `/ui` → **Run evals**.

When you switch to Azure AI Foundry, re-run the suite and compare `score` + failed case ids against mock.

## LLM providers

Set in `.env`:

| `LLM_PROVIDER` | Notes |
|----------------|-------|
| `mock` (default) | Deterministic rule-based agents — no keys needed |
| `openai` | Needs `OPENAI_API_KEY` |
| `anthropic` | Needs `ANTHROPIC_API_KEY` |
| `azure_foundry` | Claude/OpenAI via Foundry model endpoint (`AZURE_FOUNDRY_*`) |

Foundry **Agent Service** (threads/runs) is OpenAI-family only today; Claude is used via the **model endpoint** + our LangGraph orchestration — which is the skill you want to show.

## Production path (Azure)

Week-by-week target:

1. **Now** — local graph + guardrail + dry-run executor (this repo)
2. **AKS via Terraform** (`infra/terraform`) — `.\scripts\terraform_apply.ps1`
3. Wire Event Hubs / Service Bus → ingest API
4. Azure AI Search over runbooks for diagnosis RAG
5. Cost Management + Consumption APIs for cost agent
6. Key Vault secrets + App Insights / GenAI tracing
7. Live executor with RBAC-scoped ServiceAccount (still behind guardrail)
8. GitHub Actions → AKS + demo video / architecture write-up

## AKS platform (Ingress + TLS + Argo CD)

One-shot install on AKS (installs Helm if missing, nginx-ingress, cert-manager, Argo CD):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_aks_platform.ps1 -LetsEncryptEmail you@yourdomain.com
```

| Component | Namespace | Purpose |
|-----------|-----------|---------|
| nginx-ingress | `ingress-nginx` | Public HTTP/HTTPS entry (LoadBalancer IP) |
| cert-manager | `cert-manager` | Let's Encrypt TLS certificates |
| Argo CD | `argocd` | GitOps deploy from `infra/helm/acrfp` |

**DNS (required for TLS):** Point `api.acrfp.site` A-record → nginx LoadBalancer IP (`kubectl get svc -n ingress-nginx`).

Domain: **acrfp.site** (GoDaddy). See `commands.md` Week 3.5 for GoDaddy steps.

**Deploy app with HTTPS:**

```powershell
kubectl apply -f infra/k8s/ingress/api-ingress.yaml
```

Or Helm (fresh cluster only):

```powershell
helm upgrade --install acrfp infra/helm/acrfp -f infra/helm/acrfp/values-ingress.yaml
```

`acrfp-api` uses `ClusterIP`; only nginx-ingress gets a public LoadBalancer. Guardrail and executor stay internal.

## Helm and Argo CD

- Helm chart: `infra/helm/acrfp` (+ `values-ingress.yaml` for TLS)
- ClusterIssuers: `infra/platform/cluster-issuer.yaml`
- Argo CD app: `infra/argocd/acrfp-application.yaml` (replace `repoURL` with your Git repo)

## What you must be able to explain

Open and walk through line-by-line:

- `src/guardrail/policy.py` — risk classification + allow/approve/deny
- `src/orchestrator/graph.py` — triage → specialists → guardrail → executor

Do not treat those two files as generated magic. Interviewers will probe them.

## What is done vs pending

### Done (Week 1 + Phase A + Week 3 infra)
- Local multi-agent platform (LangGraph + 3 specialists + executor dry-run)
- Guardrail policy engine + HTTP proxy + `/ui` approval console
- Sample events, tests, Docker Compose, K8s manifests, CI
- Audit trail, YAML policy packs, dual approval, region lock, webhook notify
- **Terraform modules** for RG + AKS (`centralindia` cluster live)
- Architecture doc + images (`docs/architecture.md`)
- Helm chart, Ingress/TLS manifests, platform install script (`install_aks_platform.ps1`)

### Pending (next)
- **Deploy app to AKS** (`.\scripts\week3_aks_deploy.ps1`) then ingress or port-forward test
- **DNS A-record** for your domain → nginx LoadBalancer IP
- Later: Azure Foundry, Event Hubs, Cost APIs, AI Search, live executor
- Demo video + CV bullets

## New enterprise endpoints

- `GET /v1/audit`
- `GET /v1/incidents/{id}/audit`
- `GET /v1/audit/export?format=json|csv`
- `GET /v1/evals/cases` · `POST /v1/evals/run` · `GET /v1/evals`
- Approvals: HIGH risk needs 2 different `decided_by` values

Switch policy pack:

```bat
set POLICY_PACK=prod
```

## License

Portfolio project — use/modify for your job search.
