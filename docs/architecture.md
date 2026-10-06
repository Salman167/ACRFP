# ACRFP Architecture

Portfolio reference for interviews, LinkedIn, and the demo video intro.

## Full platform

![ACRFP architecture](images/acrfp-architecture.png)

**Flow:** cloud/K8s signals → API → LangGraph orchestrator (Diagnosis / Cost / Remediation) → **Guardrail** (allow / require approval / deny) → Executor (dry-run now, live later) or human queue (`/ui`).

**Interview points:**
1. Agents never call `kubectl` / ARM directly.
2. Guardrail risk comes from **action type + parameters**, not LLM self-rating.
3. Executor never runs without allow or human approval.

## Frontend vs backend

![Frontend vs Backend](images/acrfp-frontend-backend.png)

| Layer | What it is | How you reach it |
|-------|------------|------------------|
| Frontend | Approval UI (`GET /ui`) | Browser |
| Backend | FastAPI + agents + guardrail + executor | `/v1/*`, Swagger `/docs` |

Same APIs power Swagger and `/ui`. `/ui` also calls `GET /v1/summary` and `GET /v1/incidents?status=`.

Shareable copy for SharePoint: [`sharepoint/ACRFP-end-to-end-call-flow.md`](sharepoint/ACRFP-end-to-end-call-flow.md).

## End-to-end file call (from user input)

Start: `POST /v1/incidents/ingest` (Swagger, curl, or `scripts/ingest_samples.py`).

| Step | File | Function | Calls `llm.py`? |
|------|------|----------|-----------------|
| 1 | `src/api/app.py` | `ingest()` | No |
| 2 | `src/orchestrator/graph.py` | `run_incident()` → `graph.invoke()` | No |
| 3 | `graph.py` | `triage_node()` | No — `event_type` only |
| 4 | `src/agents/diagnosis.py` | `diagnose()` | **Yes** — `chat_json()` if routed |
| 5 | `src/agents/cost.py` | `analyze_cost()` | **Yes** — only if cost/mixed |
| 6 | `src/agents/remediation.py` | `propose_actions()` | Always calls `chat_json()`; mock/fail → rules |
| 7 | `src/guardrail/policy.py` | `decide()` | **Never** |
| 8 | `src/executor/app.py` | `execute()` | **Never** — only if ALLOW |
| 9 | `src/api/app.py` | `_case_from_graph()` + audit | No |

`chat_json()` lives only in `src/agents/llm.py`. `mock` returns `None` and the specialist uses rules. Guardrail and executor never import LangChain.

Human approve (`POST /v1/approvals/{id}/decide`) skips the graph and sends one parked proposal to the executor.

## Azure Week 3 layout

```text
Terraform (modules)                 App deploy script
───────────────────                 ─────────────────
module.rg  → acrfp-rg               az acr build → image in ACR
module.aks → acrfp-aks (1 node)  →  kubectl apply → api + guardrail + executor
```

| Path | Role |
|------|------|
| `infra/terraform/main.tf` | Calls modules + outputs |
| `infra/terraform/modules/rg` | Resource group |
| `infra/terraform/modules/aks` | AKS cluster |
| `infra/k8s/` | App Deployments / Services |
| `scripts/week3_aks_deploy.ps1` | ACR build + kubectl apply |

## Production ingress (DNS + TLS + Argo CD)

**Domain:** `acrfp.site` (GoDaddy)  
**App URL:** `https://api.acrfp.site`  
**Argo CD (optional):** `https://argocd.acrfp.site`

```mermaid
flowchart TB
  subgraph Internet
    User[Browser / API clients]
    LE[Let's Encrypt]
  end

  subgraph GoDaddy["GoDaddy DNS — acrfp.site"]
    A1["A  api      → nginx LB IP"]
    A2["A  argocd   → Argo CD LB IP  (optional)"]
  end

  subgraph Azure["Azure — acrfp-rg / centralindia"]
    subgraph AKS["AKS acrfp-aks"]
      NGINX[nginx-ingress LoadBalancer]
      CM[cert-manager]
      ING[Ingress api.acrfp.site + TLS]
      API[acrfp-api ClusterIP]
      GR[acrfp-guardrail]
      EX[acrfp-executor]
      ARGO[Argo CD argocd namespace]
    end
    ACR[ACR acrfp752f8b6b]
  end

  User --> A1
  A1 --> NGINX
  NGINX --> ING
  ING --> API
  API --> GR
  API --> EX
  CM --> LE
  CM --> ING
  ACR --> API
  ACR --> GR
  ACR --> EX
  User -.-> A2
  A2 -.-> ARGO
```

| Component | Namespace | Public? | Role |
|-----------|-----------|---------|------|
| nginx-ingress | `ingress-nginx` | Yes (LoadBalancer IP) | HTTPS entry, routes to app |
| cert-manager | `cert-manager` | No | Issues TLS certs via Let's Encrypt |
| acrfp-api | `default` | No (ClusterIP) | FastAPI + agents + `/ui` |
| acrfp-guardrail | `default` | No | Policy allow / deny / approve |
| acrfp-executor | `default` | No | Dry-run actions |
| Argo CD | `argocd` | Optional LB | GitOps deploy from Helm chart |

**Traffic path:** `https://api.acrfp.site` → nginx → Ingress (TLS) → `acrfp-api:80` → guardrail / executor (internal only).

## Azure AI Foundry (model only)

Foundry hosts the **LLM**. ACRFP (on AKS or laptop) stays the control plane.

```
Foundry model deployment (Claude/GPT in-region)
        ↑ chat via /openai/v1
acrfp-api  (LLM_PROVIDER=azure_foundry → src/agents/llm.py)
        → acrfp-guardrail / acrfp-executor   (no Foundry keys)
```

Wire steps and env vars: root [`README.md`](../README.md) (*Azure AI Foundry*) and [`project-journey-runbook.md`](project-journey-runbook.md) Phase 3. Do not use Foundry Agent Service as the orchestrator.

| Path | Role |
|------|------|
| `scripts/install_aks_platform.ps1` | Helm + nginx + cert-manager + Argo CD |
| `infra/platform/cluster-issuer.yaml` | Let's Encrypt staging + prod |
| `infra/helm/acrfp/` | Helm chart |
| `infra/helm/acrfp/values-ingress.yaml` | Ingress enabled for `api.acrfp.site` |
| `infra/k8s/ingress/api-ingress.yaml` | Raw Ingress (alternative to Helm) |
| `infra/argocd/acrfp-application.yaml` | Argo CD app (needs Git repo URL) |

## Image files

| Image | Path |
|-------|------|
| Full platform | `docs/images/acrfp-architecture.png` |
| Frontend vs Backend | `docs/images/acrfp-frontend-backend.png` |

---

## Full architecture — AI + DevOps (diagrams)

### Product + AI + Azure edge

```mermaid
flowchart TB
  subgraph Users["People / systems"]
    OnCall["On-call / FinOps"]
    AlertSrc["Alerts / Event Hubs later"]
  end

  subgraph Edge["DevOps edge — Azure AKS"]
    DNS["DNS api.acrfp.site"]
    NGINX["nginx Ingress + TLS<br/>cert-manager / Let's Encrypt"]
  end

  subgraph App["ACRFP control plane"]
    API["acrfp-api<br/>FastAPI + LangGraph + /ui"]
    GR["acrfp-guardrail<br/>policy.py + YAML"]
    EX["acrfp-executor<br/>dry-run kubectl/az"]
  end

  subgraph AI["AI layer — optional"]
    LLM["src/agents/llm.py chat_json()"]
    Foundry["Azure AI Foundry /openai/v1"]
    Mock["mock / rules fallback"]
  end

  subgraph Data["Config and evidence"]
    Policies["data/policies/*.yaml"]
    Runbooks["data/runbooks/*.md"]
    Evals["data/evals/golden_cases.yaml"]
    Audit["audit JSONL"]
  end

  AlertSrc --> API
  OnCall -->|"/ui approve"| API
  OnCall --> DNS
  DNS --> NGINX --> API
  API --> GR
  API --> EX
  API --> LLM
  LLM --> Foundry
  LLM --> Mock
  GR --> Policies
  API --> Runbooks
  API --> Evals
  API --> Audit
```

### AI path inside one incident

```mermaid
flowchart LR
  A["api ingest"] --> T["triage no AI"]
  T --> D["diagnosis.py"]
  T --> C["cost.py"]
  D --> L["llm.py"]
  C --> L
  D --> R["remediation.py"]
  C --> R
  R --> L
  R --> G["guardrail policy"]
  G -->|ALLOW| E["executor dry-run"]
  G -->|APPROVAL| H["/ui"]
  G -->|DENY| X["audit only"]
```

### DevOps / Azure supply chain

```mermaid
flowchart TB
  TF["Terraform RG + AKS"] --> AKS["AKS cluster"]
  Git["GitHub"] --> GHA["CI pytest mock"]
  Git --> ACR["ACR image"]
  ACR --> API2["acrfp-api"]
  ACR --> GR2["guardrail"]
  ACR --> EX2["executor"]
  Helm["Helm / Argo CD"] --> API2
  ING["nginx Ingress"] --> API2
  CM["cert-manager"] --> ING
  TF --> AKS
  AKS --> ING
  AKS --> API2
```

### Tech cheat sheet

| Concern | Technology | In this repo |
|---------|------------|--------------|
| Orchestration | LangGraph | `src/orchestrator/graph.py` |
| Models | LangChain + mock / OpenAI / Anthropic / Foundry | `src/agents/llm.py` |
| Safety | Policy-as-code guardrails | `guardrail/policy.py` + YAML |
| Execution | Dry-run executor | `src/executor/app.py` |
| Humans | Approval UI | `GET /ui` |
| Quality | Golden evals | `src/evals/` |
| Hosting | Terraform, AKS, Helm, Ingress, Argo CD, GHA | `infra/` + `.github/` |
| Vector RAG | **Not wired** — keyword runbooks today; Qdrant or Azure AI Search later | see below |

---

## Qdrant — what it is (and how it would fit ACRFP)

**Qdrant is not in this repo today.** Diagnosis uses **keyword match** over `data/runbooks/*.md`. Qdrant (or Azure AI Search) is the natural next step when runbooks grow.

### What Qdrant is

**Qdrant** is an open-source **vector database**. You store embeddings (number arrays) of text chunks. At query time you embed the incident title/description and retrieve the nearest runbook passages by similarity — even when the wording differs (“pods keep dying” ≈ “CrashLoopBackOff”).

| Term | Meaning |
|------|---------|
| Embedding | Vector from an embedding model (OpenAI / Foundry / local) |
| Collection | Table of vectors + payload (runbook id, text, tags) |
| Similarity search | Top-K chunks closest to the query vector |
| Hybrid search | Vectors + keyword filters (namespace, severity) |

It is **retrieval**, not the orchestrator and not the guardrail. It does not decide allow/deny.

### Today vs with Qdrant

```text
TODAY
  incident text → keyword match runbooks/*.md → diagnosis (+ optional LLM)

WITH QDRANT (planned pattern)
  ingest runbooks → chunk → embed → upsert into Qdrant
  incident text → embed → Qdrant top-K → pass chunks into diagnosis prompt → LLM JSON
  → remediation → guardrail (unchanged) → executor
```

```mermaid
flowchart LR
  RB["runbooks MD"] --> CH["chunk + embed"]
  CH --> QD["Qdrant collection"]
  INC["incident"] --> EMB["embed query"]
  EMB --> QD
  QD --> CTX["top-K passages"]
  CTX --> DIAG["diagnosis.py + llm.py"]
  DIAG --> REM["remediation"]
  REM --> POL["guardrail — unchanged"]
```

### How you would integrate it (interview / roadmap)

1. Run Qdrant (Docker locally, or Helm on AKS).
2. Offline job: chunk `data/runbooks/`, call an embedding API, `upsert` into a collection (e.g. `acrfp_runbooks`).
3. In `diagnosis.py`, replace/extend `_keyword_match` with: embed event text → `client.search(...)` → top 3–5 passages in the prompt to `chat_json()`.
4. Keep **guardrail and executor untouched**.
5. Alternative on Azure-only stacks: **Azure AI Search** instead of Qdrant (same RAG role; better fit for Foundry + private networking). This repo’s roadmap mentions AI Search; Qdrant is the portable open-source equivalent (also used in other portfolio RAG work).

### When you need it vs not

| Situation | Use |
|-----------|-----|
| Few markdown runbooks, clear titles | Keyword match (current) is enough |
| Dozens/hundreds of runbooks, synonyms, multi-language | Qdrant or Azure AI Search |
| Safety / kubectl | Never — still `policy.py` |

**Interview line:** *Qdrant would be our vector store for runbook RAG. Today we keyword-match a small corpus. Scaling retrieval does not change LangGraph or the guardrail — only how diagnosis gathers context before `llm.py`.*
