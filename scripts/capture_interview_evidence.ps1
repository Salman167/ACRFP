#Requires -Version 5.1
<#
.SYNOPSIS
  Captures live ACRFP screenshots + API JSON for interview evidence (offline pack).

.EXAMPLE
  .\scripts\capture_interview_evidence.ps1
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "docs\interview-evidence"
$Shot = Join-Path $Out "screenshots"
$Dump = Join-Path $Out "api-dumps"
New-Item -ItemType Directory -Force -Path $Shot, $Dump | Out-Null

$Base = if ($env:ACRFP_BASE_URL) { $env:ACRFP_BASE_URL.TrimEnd("/") } else { "https://api.acrfp.site" }
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Base URL: $Base"
Write-Host "Output:   $Out"

function Save-Api([string]$Name, [string]$PathSuffix) {
  $dest = Join-Path $Dump $Name
  Write-Host ("GET {0}{1} -> {2}" -f $Base, $PathSuffix, $Name)
  & curl.exe -sS -o $dest ($Base + $PathSuffix)
  if (-not (Test-Path $dest) -or ((Get-Item $dest).Length -lt 2)) {
    Write-Warning ("Empty or missing: {0}" -f $Name)
  }
}

Save-Api "01-health.json" "/health"
Save-Api "02-incidents.json" "/v1/incidents"
Save-Api "03-audit.json" "/v1/audit?limit=50"
Save-Api "04-approvals-pending.json" "/v1/approvals/pending"

$shotScript = @'
from pathlib import Path
import os
import sys

base = os.environ["ACRFP_BASE_URL"].rstrip("/")
shot = Path(os.environ["ACRFP_SHOT_DIR"])
shot.mkdir(parents=True, exist_ok=True)

pages = [
    ("01-health.png", base + "/health", 1280, 720, None),
    ("02-swagger-docs.png", base + "/docs", 1440, 900, "div.swagger-ui"),
    ("03-approval-ui.png", base + "/ui", 1440, 1000, "text=Approval"),
]

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed", file=sys.stderr)
    sys.exit(2)

with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, url, w, h, wait in pages:
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(url, wait_until="networkidle", timeout=60000)
        if wait:
            try:
                page.wait_for_selector(wait, timeout=25000)
            except Exception:
                page.wait_for_timeout(4000)
        else:
            page.wait_for_timeout(800)
        # Swagger UI often needs a beat after selector appears
        if "docs" in url:
            page.wait_for_timeout(2000)
        out = shot / name
        page.screenshot(path=str(out), full_page=True)
        print("OK", name, out.stat().st_size)
        page.close()
    browser.close()
'@

$env:ACRFP_BASE_URL = $Base
$env:ACRFP_SHOT_DIR = $Shot
$tmpPy = Join-Path $env:TEMP "acrfp_capture_shots.py"
Set-Content -Path $tmpPy -Value $shotScript -Encoding UTF8

Write-Host "Capturing screenshots with Playwright..."
& $Python $tmpPy
if ($LASTEXITCODE -ne 0) {
  Write-Warning "Playwright capture failed. Falling back to Chrome headless."
  $Chrome = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LocalAppData "Google\Chrome\Application\chrome.exe")
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $Chrome) { throw "Chrome not found and Playwright failed." }
  $UserData = Join-Path $env:TEMP "acrfp-chrome-evidence"
  New-Item -ItemType Directory -Force -Path $UserData | Out-Null
  $pages = @(
    @{ Name = "01-health.png"; Url = "$Base/health"; W = 1280; H = 720 },
    @{ Name = "02-swagger-docs.png"; Url = "$Base/docs"; W = 1440; H = 900 },
    @{ Name = "03-approval-ui.png"; Url = "$Base/ui"; W = 1440; H = 1000 }
  )
  foreach ($p in $pages) {
    $file = Join-Path $Shot $p.Name
    Write-Host ("Screenshot {0} -> {1}" -f $p.Url, $p.Name)
    & $Chrome --headless=new --disable-gpu --hide-scrollbars `
      --window-size="$($p.W),$($p.H)" --user-data-dir="$UserData" `
      --virtual-time-budget=20000 --run-all-compositor-stages-before-draw `
      --screenshot="$file" $p.Url | Out-Null
    Start-Sleep -Seconds 3
    if (Test-Path $file) {
      $len = (Get-Item $file).Length
      Write-Host ("  OK {0} ({1} bytes)" -f $p.Name, $len)
    } else {
      Write-Warning ("  Missing screenshot: {0}" -f $p.Name)
    }
  }
}

$kDir = Join-Path $Dump "kubectl"
New-Item -ItemType Directory -Force -Path $kDir | Out-Null
$Kubectl = Get-Command kubectl -ErrorAction SilentlyContinue
if ($Kubectl) {
  Write-Host "Capturing kubectl status (namespace=default)..."
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  kubectl get pods -n default -o wide 2>$null | Out-File -Encoding utf8 (Join-Path $kDir "pods.txt")
  kubectl get ingress -A -o wide 2>$null | Out-File -Encoding utf8 (Join-Path $kDir "ingress.txt")
  kubectl get certificate -A 2>$null | Out-File -Encoding utf8 (Join-Path $kDir "certificates.txt")
  kubectl get svc -n ingress-nginx 2>$null | Out-File -Encoding utf8 (Join-Path $kDir "ingress-nginx-svc.txt")
  $ErrorActionPreference = $prev
}

Write-Host ""
Write-Host "Done. Open docs/interview-evidence/INTERVIEW_DEMO.html in a browser (offline OK)."
Write-Host "Then stop AKS if you want to save cost:"
Write-Host "  az aks stop -g acrfp-rg -n acrfp-aks"
