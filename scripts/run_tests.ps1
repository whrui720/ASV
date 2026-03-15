# PowerShell Test Runner for hybrid_citation_scraper
# Usage: .\scripts\run_tests.ps1 [options]

param(
    [switch]$Coverage,
    [switch]$Verbose,
    [switch]$Fast,
    [switch]$HtmlReport,
    [string]$Module,
    [string]$Markers,
    [int]$Parallel
)

Write-Host "Hybrid Citation Scraper Test Runner" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# Ensure paths resolve from repository root even when called from elsewhere
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

# Build pytest command
$cmd = @("pytest")

# Add verbosity
if ($Verbose) {
    $cmd += "-vv"
} else {
    $cmd += "-v"
}

# Add coverage
if ($Coverage) {
    $cmd += "--cov=hybrid_citation_scraper"
    $cmd += "--cov-report=term-missing"
    
    if ($HtmlReport) {
        $cmd += "--cov-report=html"
    }
}

# Add marker filtering
if ($Fast) {
    $cmd += "-m"
    $cmd += "not slow"
}

if ($Markers) {
    $cmd += "-m"
    $cmd += $Markers
}

# Add parallel execution
if ($Parallel -gt 0) {
    $cmd += "-n"
    $cmd += $Parallel
}

# Add specific module
if ($Module) {
    $testFile = "hybrid_citation_scraper/tests/test_$Module.py"
    if (-not (Test-Path $testFile)) {
        Write-Host "Error: Test file not found: $testFile" -ForegroundColor Red
        Write-Host "Available modules: utils, llm_client, claim_extractor, config, integration" -ForegroundColor Yellow
        exit 1
    }
    $cmd += $testFile
} else {
    $cmd += "hybrid_citation_scraper/tests/"
}

# Print command
Write-Host "Running: $($cmd -join ' ')" -ForegroundColor Green
Write-Host ("-" * 60)
Write-Host ""

# Run pytest
try {
    & $cmd[0] $cmd[1..($cmd.Length-1)]
    $exitCode = $LASTEXITCODE
    
    Write-Host ""
    Write-Host ("-" * 60)
    
    if ($exitCode -eq 0) {
        Write-Host "All tests passed!" -ForegroundColor Green
    } else {
        Write-Host "Some tests failed (exit code: $exitCode)" -ForegroundColor Red
    }
    
    if ($Coverage -and $HtmlReport) {
        Write-Host ""
        Write-Host "Coverage report generated: htmlcov/index.html" -ForegroundColor Cyan
    }
    
    exit $exitCode
}
catch {
    Write-Host "Error running tests: $_" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
