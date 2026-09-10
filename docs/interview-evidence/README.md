# ACRFP — Interview Demo Pack (show this when AKS is stopped)

**Open offline:** [`INTERVIEW_DEMO.html`](INTERVIEW_DEMO.html) (double-click in Chrome/Edge).  
That file is the interviewer-facing walkthrough with diagrams, screenshots, and JSON evidence.

Use this Markdown as a speaking outline; use the HTML as the screen share.

---

## Why this exists

Interviewers often ask you to “walk through the project.” The live AKS demo may be **stopped to save Azure credits**. This pack proves you built and ran it **end-to-end** without needing the cluster up during the call.

---

## Capture screenshots (do this once while AKS is up)

```powershell
cd c:\Users\Administrator\OneDrive\Desktop\salman_genai\Multi_agents
$env:Path = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;" + $env:Path

# If cluster was stopped:
# az aks start -g acrfp-rg -n acrfp-aks
# az aks get-credentials -g acrfp-rg -n acrfp-aks --overwrite-existing

.\scripts\capture_interview_evidence.ps1
```

This writes:

| Output | Purpose |
|--------|---------|
| `screenshots/01-health.png` | HTTPS health page |
| `screenshots/02-swagger-docs.png` | `/docs` OpenAPI |
| `screenshots/03-approval-ui.png` | `/ui` human approvals |
| `api-dumps/*.json` | health / incidents / audit / pending |
| `api-dumps/kubectl/*.txt` | pods, ingress, certs (if kubectl works) |

Then stop AKS:

```powershell
az aks stop -g acrfp-rg -n acrfp-aks
```

---

## 60-second pitch

> I built **ACRFP** — an agentic Cloud Reliability & FinOps control plane.  
> Incidents hit a FastAPI API on AKS. LangGraph agents propose diagnosis, cost, and remediation.  
> A **guardrail** decides allow / require approval / deny. High-risk actions go to a dual-approval UI.  
> Execution today is **dry-run** with a full **audit trail**. Public HTTPS is on `api.acrfp.site` via Ingress + Let’s Encrypt.

---

## Screen-share order (HTML sections)

1. **Architecture diagrams** — agents never touch kubectl directly.  
2. **Health + Swagger screenshots** — real public HTTPS deploy.  
3. **Approval UI screenshot** — human-in-the-loop.  
4. **JSON dumps** — incidents + audit prove the pipeline ran.  
5. **Honest scope** — Foundry / live executor are next (don’t overclaim).

---

## Manual screenshots (if script fails)

While `https://api.acrfp.site` works, save PNGs into `docs/interview-evidence/screenshots/`:

1. Open `/health` → Save as `01-health.png`  
2. Open `/docs` → Save as `02-swagger-docs.png`  
3. Open `/ui` → Save as `03-approval-ui.png`  
4. Optional: Azure Portal AKS overview, Ingress IP, GoDaddy DNS A record  

Also paste API JSON into `api-dumps/` if needed:

```powershell
curl.exe -o docs\interview-evidence\api-dumps\01-health.json https://api.acrfp.site/health
curl.exe -o docs\interview-evidence\api-dumps\02-incidents.json https://api.acrfp.site/v1/incidents
curl.exe -o docs\interview-evidence\api-dumps\03-audit.json "https://api.acrfp.site/v1/audit?limit=50"
```

---

## Companion docs

| Doc | Audience |
|-----|----------|
| [`INTERVIEW_DEMO.html`](INTERVIEW_DEMO.html) | Interviewer (visual) |
| [`../project-journey-runbook.md`](../project-journey-runbook.md) | Deep commands + issues/fixes |
| [`../architecture.md`](../architecture.md) | Architecture narrative |

---

## Do / don’t in interview

**Do:** show guardrail + approval + audit as the enterprise story.  
**Do:** say dry-run is intentional for safe demo.  
**Don’t:** claim live Azure mutations or Foundry-in-prod until wired.  
**Don’t:** depend on AKS being up — rely on this pack.
