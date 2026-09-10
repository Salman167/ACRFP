# Deploy ACRFP to AKS - build image in ACR (cloud or local Docker fallback).
param(
    [string]$ResourceGroup = "acrfp-rg",
    [string]$ClusterName = "acrfp-aks",
    [string]$Location = "centralindia",
    [string]$AcrName = "acrfp752f8b6b",
    [string]$ImageTag = "dev",
    [ValidateSet("auto", "cloud", "local")]
    [string]$BuildMethod = "auto"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$K8sDir = Join-Path $Root "infra\k8s"
$BuildDir = Join-Path $Root "infra\k8s-rendered"
$ImageName = "acrfp-api"
$FullImage = "$AcrName.azurecr.io/${ImageName}:$ImageTag"

$azBin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azBin) { $env:Path = "$azBin;$env:Path" }

function Test-DockerDaemon {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker info 1>$null 2>$null
    $ok = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $prevEap
    return $ok
}

function Start-DockerDesktopIfNeeded {
    if (Test-DockerDaemon) { return $true }
    $dockerDesktop = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktop)) { return $false }
    Write-Host "Starting Docker Desktop (wait ~30-60s)..." -ForegroundColor Yellow
    Start-Process $dockerDesktop | Out-Null
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 5
        if (Test-DockerDaemon) { return $true }
    }
    return $false
}

function Build-ImageInAcrCloud {
    Write-Host "Building image in ACR cloud (5-8 min)..." -ForegroundColor Cyan
    Push-Location $Root
    try {
        az acr build --registry $AcrName --image "${ImageName}:$ImageTag" . --output table
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        Pop-Location
    }
}

function Build-ImageLocally {
    if (-not (Test-DockerDaemon)) {
        if (-not (Start-DockerDesktopIfNeeded)) {
            throw @"
Docker is not running. Free/trial Azure blocks 'az acr build' (ACR Tasks).

Fix:
  1) Start Docker Desktop from the Start menu
  2) Wait until it says 'Docker is running'
  3) Re-run: powershell -ExecutionPolicy Bypass -File .\scripts\week3_aks_deploy.ps1 -BuildMethod local

Or upgrade Azure subscription to Pay-As-You-Go and use -BuildMethod cloud.
"@
        }
    }

    Write-Host "Building image locally and pushing to ACR..." -ForegroundColor Cyan
    az acr login --name $AcrName
    if ($LASTEXITCODE -ne 0) { throw "az acr login failed" }

    Push-Location $Root
    try {
        docker build -t $FullImage .
        if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
        docker push $FullImage
        if ($LASTEXITCODE -ne 0) { throw "docker push failed" }
    }
    finally {
        Pop-Location
    }
}

Write-Host "=== ACRFP deploy to AKS ===" -ForegroundColor Cyan
Write-Host "RG=$ResourceGroup Cluster=$ClusterName ACR=$AcrName BuildMethod=$BuildMethod"

az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { throw "Run: az login --use-device-code" }

az aks get-credentials --resource-group $ResourceGroup --name $ClusterName --overwrite-existing

# 1) Azure Container Registry
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
az acr show --name $AcrName --resource-group $ResourceGroup -o none 2>$null | Out-Null
$acrMissing = $LASTEXITCODE -ne 0
$ErrorActionPreference = $prevEap
if ($acrMissing) {
    Write-Host "Creating ACR '$AcrName' (Basic SKU)..."
    az acr create --resource-group $ResourceGroup --name $AcrName --sku Basic --location $Location -o table
    if ($LASTEXITCODE -ne 0) { throw "ACR create failed" }
}

# 2) Build + push image
$built = $false
if ($BuildMethod -eq "local") {
    Build-ImageLocally
    $built = $true
}
elseif ($BuildMethod -eq "cloud") {
    if (-not (Build-ImageInAcrCloud)) { throw "ACR cloud build failed" }
    $built = $true
}
else {
    if (Build-ImageInAcrCloud) {
        $built = $true
    }
    else {
        Write-Host "ACR cloud build blocked (common on free/trial). Trying local Docker..." -ForegroundColor Yellow
        Build-ImageLocally
        $built = $true
    }
}
if (-not $built) { throw "Image build failed" }

# 3) Let AKS pull from your private registry
Write-Host "Attaching ACR to AKS..."
az aks update --resource-group $ResourceGroup --name $ClusterName --attach-acr $AcrName -o none

# 4) Render K8s YAML with real image URL
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
Get-ChildItem $K8sDir -Filter "*.yaml" | ForEach-Object {
    $text = Get-Content $_.FullName -Raw
    $text = $text -replace "acrfp/api:dev", $FullImage
    $text = $text -replace "value: azure", "value: local"  # safe dry-run on AKS practice
    Set-Content -Path (Join-Path $BuildDir $_.Name) -Value $text -Encoding UTF8
}
Write-Host "Using image: $FullImage"

# 5) Apply to cluster
Write-Host "Applying Kubernetes manifests..."
kubectl apply -f $BuildDir

Write-Host "Waiting for API pod (up to 3 min)..."
kubectl wait --for=condition=ready pod -l app=acrfp-api --timeout=180s 2>$null

Write-Host ""
Write-Host "Pods:" -ForegroundColor Green
kubectl get pods -o wide
kubectl get svc

Write-Host ""
Write-Host "=== TEST on AKS ===" -ForegroundColor Green
Write-Host 'Option A - port-forward (free, in a new terminal):'
Write-Host "  kubectl port-forward svc/acrfp-api 8010:80"
Write-Host "  Then open: http://127.0.0.1:8010/ui"
Write-Host "  Ingest from your PC:"
Write-Host "  .\.venv\Scripts\python.exe scripts\ingest_samples.py http://127.0.0.1:8010"
Write-Host ""
Write-Host 'Option B - LoadBalancer (costs a small IP fee):'
Write-Host '  kubectl patch svc acrfp-api -p ''{"spec":{"type":"LoadBalancer"}}'''
Write-Host "  kubectl get svc acrfp-api -w"
Write-Host ""
Write-Host "When done today, delete infra with Terraform:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\terraform_destroy.ps1"
