# ACRFP — End-to-end call flow (SharePoint)

Upload this page to SharePoint or attach it to a job application. It is the same story as the repo README.

**Product:** Agentic Cloud Reliability & FinOps Platform. An alert goes in. Agents propose a typed fix. Policy decides. Only then does a dry-run run.

**One line:** you POST an event → API → LangGraph → specialists (they alone call `llm.py`) → guardrail → maybe executor → you get a case.

---

## Start: user input

You do **not** call `llm.py` yourself.

```
POST /v1/incidents/ingest
```

Example body:

```json
{
  "event_type": "reliability",
  "title": "payments-api restart storm",
  "namespace": "payments",
  "resource": "payments-api",
  "metrics": { "restarts": 9, "memory_pct": 93 }
}
```

Send it from Swagger (`/docs`), curl, or `scripts/ingest_samples.py`. Opening `/ui` is a different path (approve / refresh) and does not run the model.

---

## Step by step (which file is next)

### 1. API — `src/api/app.py` → `ingest()`

Builds an `IncidentEvent`. Calls:

```text
run_incident(event.model_dump())
```

No LangChain. Next file: orchestrator.

### 2. Orchestrator — `src/orchestrator/graph.py` → `run_incident()`

`graph.invoke(initial)` walks nodes. Shared state: `src/orchestrator/state.py`.

For `reliability`:

```text
START → triage → diagnosis → remediate → guardrail → executor (if ALLOW) → END
```

### 3. `triage_node()` — no `llm.py`

| event_type | Next specialists |
|------------|------------------|
| reliability | diagnosis |
| cost | cost |
| mixed | diagnosis then cost |

This example → `route_plan = ["diagnosis"]`.

### 4. Diagnosis — first possible model call

`graph.py` `diagnosis_node()` → `src/agents/diagnosis.py` `diagnose()`

1. Load `data/runbooks/*.md` (keyword RAG).
2. Call **`src/agents/llm.py` `chat_json()`**.
3. If `LLM_PROVIDER=mock` (default), `chat_json` returns `None` and rules run (`restarts > 3` → CrashLoop).

Result: `DiagnosisResult` in graph state.

### 5. Remediation — second possible model call

`graph.py` `remediate_node()` → `src/agents/remediation.py` `propose_actions()`

Calls **`llm.py` `chat_json()` again**. Mock → `_rule_based_proposals()` → `restart_pod` on `payments-api`.

Result: list of `ActionProposal`. **The model is finished for this ingest.**

### 6. Guardrail — never `llm.py`

`graph.py` `guardrail_node()` → HTTP `src/guardrail/app.py` `/v1/evaluate/batch`  
or in-process `src/guardrail/policy.py` `decide()`.

Risk from **action type + parameters + namespace + region**, not the model’s `risk_hint` (hint can only raise risk).

This example: `restart_pod` in `payments` → LOW → **ALLOW**.

### 7. Executor — never `llm.py`

Only if ALLOW. `src/executor/app.py` records:

```text
kubectl rollout restart deployment/payments-api -n payments
```

Dry-run. Cluster is not changed.

### 8. Back to the API

`_case_from_graph()` + `src/shared/audit.py`. You receive `incident_id`, `status`, full case.

---

## Who may call `llm.py`

| File | Calls `chat_json()`? |
|------|----------------------|
| `src/agents/diagnosis.py` | Yes, if diagnosis ran |
| `src/agents/cost.py` | Yes, if cost/mixed |
| `src/agents/remediation.py` | Always calls `chat_json()`; mock/fail → rule proposals |
| `src/api/app.py` | No |
| `src/orchestrator/graph.py` | No (it only calls the three agents) |
| `src/guardrail/policy.py` | **Never** |
| `src/executor/app.py` | **Never** |

`chat_json()` providers: `mock` | `openai` | `anthropic` | `azure_foundry`. Failure or mock → `None` → rules.

---

## Azure AI Foundry (how you switch the model)

You deploy a **model** in Foundry; you do not deploy ACRFP into Foundry.

1. Foundry portal → deploy Claude/GPT in an allow-list region → copy endpoint, key, deployment name.
2. Set `LLM_PROVIDER=azure_foundry` plus `AZURE_FOUNDRY_ENDPOINT`, `AZURE_FOUNDRY_API_KEY`, `AZURE_FOUNDRY_DEPLOYMENT`.
3. Restart API (local uvicorn or `acrfp-api` on AKS). Only the API needs these vars.
4. Re-ingest + run golden evals; compare score to mock.
5. Keep using the **model endpoint** (`…/openai/v1` via `llm.py`), not Foundry Agent Service.

Details: root `README.md` → *Azure AI Foundry*.

---

## Other user inputs (not ingest)

| You do | Files | `llm.py`? |
|--------|-------|-----------|
| Open `/ui` | `api/app.py` serves HTML; JS calls `/v1/summary`, `/v1/incidents`, `/v1/approvals/pending` | No |
| Approve | `decide_approval()` → `_execute_proposal()` → executor | No — graph is not re-run |
| Run evals | `evals/harness.py` → `run_incident()` per golden case | Same as ingest (`mock` → still `None`) |

---

## Other sample endings

- **Idle VM (`cost`):** triage → cost (`llm.py`) → remediate (`llm.py`) → MEDIUM → park on `/ui`. No executor until a human approves.
- **CoreDNS in `kube-system`:** restart proposal → HIGH → two different approvers.
- **Region `us-east-1`:** guardrail **DENY** (`POL-REGION-LOCK-001`).

---

## Non-negotiables

1. Agents never call `kubectl` / ARM.
2. Guardrail risk is not LLM self-rating.
3. Executor never runs without allow or human approval.

Repo: https://github.com/Salman167/ACRFP  
Live host (when AKS is up): `https://api.acrfp.site`
