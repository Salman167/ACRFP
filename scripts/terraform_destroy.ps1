# Terraform destroy - delete RG + AKS (stop VM billing)
$ErrorActionPreference = "Stop"
$TfDir = Join-Path (Split-Path -Parent $PSScriptRoot) "infra\terraform"
$azBin = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin"
if (Test-Path $azBin) { $env:Path = "$azBin;$env:Path" }

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Host "Terraform not found. Fallback: az group delete --name acrfp-rg --yes" -ForegroundColor Yellow
    az group delete --name acrfp-rg --yes --no-wait
    az group delete --name acrfp-rg-in --yes --no-wait
    exit 0
}

Push-Location $TfDir
terraform destroy -auto-approve
Pop-Location

Write-Host "Terraform destroy complete. Also remove any old script RGs if they still exist:" -ForegroundColor Green
Write-Host "  az group delete --name acrfp-rg-in --yes --no-wait"
