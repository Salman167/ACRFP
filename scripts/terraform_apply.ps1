# Terraform apply - create RG + AKS (single infra path)
$ErrorActionPreference = "Stop"
$TfDir = Join-Path (Split-Path -Parent $PSScriptRoot) "infra\terraform"
$azBin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azBin) { $env:Path = "$azBin;$env:Path" }

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Host "Terraform not found. Install: winget install -e --id Hashicorp.Terraform" -ForegroundColor Red
    exit 1
}

az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { throw "Run: az login --use-device-code" }

Push-Location $TfDir
terraform init
terraform plan
terraform apply -auto-approve
$rg = terraform output -raw resource_group
$aks = terraform output -raw aks_name
Pop-Location

Write-Host ""
Write-Host "AKS ready: $aks in $rg" -ForegroundColor Green
Write-Host "Next: az aks get-credentials --resource-group $rg --name $aks --overwrite-existing"
Write-Host "Then: powershell -ExecutionPolicy Bypass -File .\scripts\week3_aks_deploy.ps1"
