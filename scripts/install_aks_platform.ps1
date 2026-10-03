# Install Helm (if missing), nginx-ingress, cert-manager, and Argo CD on AKS.
param(
    [string]$ResourceGroup = "acrfp-rg",
    [string]$ClusterName = "acrfp-aks",
    [string]$LetsEncryptEmail = "you@example.com",
    [ValidateSet("staging", "prod")]
    [string]$CertIssuer = "prod",
    [switch]$SkipClusterIssuer,
    [switch]$SkipArgoCd
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PlatformDir = Join-Path $Root "infra\platform"
$IssuerFile = Join-Path $PlatformDir "cluster-issuer.yaml"

$azBin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azBin) { $env:Path = "$azBin;$env:Path" }

function Ensure-Helm {
    $wingetHelm = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "helm.exe" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if ($wingetHelm) {
        $env:Path = "$(Split-Path $wingetHelm -Parent);$env:Path"
    }
    $helmLink = "$env:LOCALAPPDATA\Microsoft\WinGet\Links"
    if (Test-Path $helmLink) { $env:Path = "$helmLink;$env:Path" }

    if (Get-Command helm -ErrorAction SilentlyContinue) {
        Write-Host "Helm already installed: $(helm version --short)" -ForegroundColor Green
        return
    }

    Write-Host "Installing Helm via winget..." -ForegroundColor Cyan
    winget install -e --id Helm.Helm --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null

    $wingetHelm = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "helm.exe" -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if ($wingetHelm) {
        $env:Path = "$(Split-Path $wingetHelm -Parent);$env:Path"
    }

    if (-not (Get-Command helm -ErrorAction SilentlyContinue)) {
        throw "Helm installed but not on PATH. Open a new terminal and re-run this script."
    }
    Write-Host "Helm installed: $(helm version --short)" -ForegroundColor Green
}

function Wait-Deployment {
    param([string]$Namespace, [string]$Label, [int]$TimeoutSeconds = 300)
    kubectl wait --namespace $Namespace `
        --for=condition=available deployment `
        -l $Label `
        --timeout="${TimeoutSeconds}s"
}

Write-Host "=== ACRFP platform install (Helm + Ingress + TLS + Argo CD) ===" -ForegroundColor Cyan

az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { throw "Run: az login --use-device-code" }

Ensure-Helm

Write-Host "Connecting to AKS: $ClusterName in $ResourceGroup" -ForegroundColor Cyan
az aks get-credentials --resource-group $ResourceGroup --name $ClusterName --overwrite-existing
if ($LASTEXITCODE -ne 0) { throw "Failed to get AKS credentials" }

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx 2>$null
helm repo add jetstack https://charts.jetstack.io 2>$null
if (-not $SkipArgoCd) {
    helm repo add argo https://argoproj.github.io/argo-helm 2>$null
}
helm repo update

Write-Host "Installing nginx-ingress..." -ForegroundColor Cyan
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx `
    --namespace ingress-nginx `
    --create-namespace `
    --set controller.service.type=LoadBalancer `
    --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz `
    --wait --timeout 10m
if ($LASTEXITCODE -ne 0) { throw "nginx-ingress install failed" }

Write-Host "Installing cert-manager..." -ForegroundColor Cyan
helm upgrade --install cert-manager jetstack/cert-manager `
    --namespace cert-manager `
    --create-namespace `
    --set crds.enabled=true `
    --wait --timeout 10m
if ($LASTEXITCODE -ne 0) { throw "cert-manager install failed" }

if (-not $SkipClusterIssuer) {
    if ($LetsEncryptEmail -eq "you@example.com") {
        Write-Host "WARNING: Set -LetsEncryptEmail to your real email for Let's Encrypt." -ForegroundColor Yellow
    }

    $issuerYaml = Get-Content $IssuerFile -Raw
    $issuerYaml = $issuerYaml -replace "you@example.com", $LetsEncryptEmail
    $tempIssuer = Join-Path $env:TEMP "acrfp-cluster-issuer.yaml"
    Set-Content -Path $tempIssuer -Value $issuerYaml -Encoding UTF8

    Write-Host "Applying ClusterIssuers (staging + prod)..." -ForegroundColor Cyan
    kubectl apply -f $tempIssuer
    if ($LASTEXITCODE -ne 0) { throw "ClusterIssuer apply failed" }
}

if (-not $SkipArgoCd) {
    Write-Host "Installing Argo CD..." -ForegroundColor Cyan
    helm upgrade --install argocd argo/argo-cd `
        --namespace argocd `
        --create-namespace `
        --set server.service.type=LoadBalancer `
        --wait --timeout 10m
    if ($LASTEXITCODE -ne 0) { throw "Argo CD install failed" }
}

Write-Host ""
Write-Host "Waiting for ingress external IP (up to 5 min)..." -ForegroundColor Cyan
$ingressIp = $null
for ($i = 0; $i -lt 30; $i++) {
  $ingressIp = kubectl get svc ingress-nginx-controller -n ingress-nginx `
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
  if ($ingressIp) { break }
  Start-Sleep -Seconds 10
}

Write-Host ""
Write-Host "=== Platform ready ===" -ForegroundColor Green
kubectl get pods -n ingress-nginx
kubectl get pods -n cert-manager
if (-not $SkipArgoCd) { kubectl get pods -n argocd }

Write-Host ""
Write-Host "Ingress LoadBalancer IP: $(if ($ingressIp) { $ingressIp } else { '(still pending — run: kubectl get svc -n ingress-nginx)' })" -ForegroundColor Green

Write-Host ""
Write-Host "=== DNS setup (required for TLS) ===" -ForegroundColor Yellow
Write-Host "1. In your DNS provider, create an A record:"
Write-Host "     api.yourdomain.com  ->  $ingressIp"
Write-Host "2. Edit infra/helm/acrfp/values-ingress.yaml and set ingress.host to your real hostname."
Write-Host "3. Deploy app with ingress:"
Write-Host "     helm upgrade --install acrfp infra/helm/acrfp -f infra/helm/acrfp/values-ingress.yaml"
Write-Host "   Or apply raw manifest after editing host:"
Write-Host "     kubectl apply -f infra/k8s/ingress/api-ingress.yaml"
Write-Host ""
Write-Host "Test with staging issuer first (avoids Let's Encrypt rate limits):"
Write-Host "  Set clusterIssuer: letsencrypt-staging in values-ingress.yaml"

if (-not $SkipArgoCd) {
    Write-Host ""
    Write-Host "=== Argo CD ===" -ForegroundColor Yellow
    Write-Host "Initial admin password:"
    Write-Host "  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(`$_)) }"
    Write-Host "Argo CD UI (after EXTERNAL-IP is assigned):"
    Write-Host "  kubectl get svc argocd-server -n argocd"
    Write-Host "Register app (edit repoURL in infra/argocd/acrfp-application.yaml first):"
    Write-Host "  kubectl apply -f infra/argocd/acrfp-application.yaml"
}
