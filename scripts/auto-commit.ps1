param(
    [int]$IntervalSeconds = 20,
    [string]$Branch = "main",
    [string]$Remote = "origin"
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$ts] $Message"
}

Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".git")) {
    throw "No se encontró un repositorio git en $(Get-Location)"
}

# Asegurar rama activa
git checkout $Branch | Out-Null

Write-Log "Auto-commit activo en rama '$Branch' (intervalo: $IntervalSeconds s)."
Write-Log "Se omiten archivos según .gitignore."

while ($true) {
    try {
        git add -A
        git diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            $msg = "chore(auto): snapshot $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
            git commit -m $msg | Out-Null
            git push $Remote $Branch | Out-Null
            Write-Log "Commit + push realizados."
        }
    } catch {
        Write-Log "Error en auto-commit: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $IntervalSeconds
}
