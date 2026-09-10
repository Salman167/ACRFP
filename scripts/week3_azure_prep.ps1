# Week 3 prep - verify Azure login before Terraform (infra is Terraform-only).
$azBin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azBin) { $env:Path = "$azBin;$env:Path" }

Write-Host "=== ACRFP Week 3 - Azure login check ===" -ForegroundColor Cyan

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "Install Azure CLI: winget install -e --id Microsoft.AzureCLI" -ForegroundColor Red
    exit 1
}

az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Run: az login --use-device-code" -ForegroundColor Red
    exit 1
}

az account show --query "{name:name, id:id, tenant:tenantId}" -o table

Write-Host ""
Write-Host "Infra (RG + AKS) is Terraform-only. Next:" -ForegroundColor Green
Write-Host "  1) Remove old script AKS if any: az group delete --name acrfp-rg-in --yes --no-wait"
Write-Host "  2) Remove old westeurope RG if name conflict: az group delete --name acrfp-rg --yes --no-wait"
Write-Host "  3) winget install -e --id Hashicorp.Terraform"
Write-Host "  4) powershell -ExecutionPolicy Bypass -File .\scripts\terraform_apply.ps1"
