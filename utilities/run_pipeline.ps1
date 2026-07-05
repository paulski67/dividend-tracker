"Pipeline started $(Get-Date)" |
Out-File "logs\startup_check.log" -Append

Write-Host "==================================="
Write-Host "DIVIDEND TRACKER PIPELINE"
Write-Host "Started: $(Get-Date)"
Write-Host "==================================="

Set-Location "C:\Users\pauls\Documents\dev\python\proj\Dividend-Tracker-2-0"

#Clean up logs\run_pipeline_$stamp
$logDir = ".\logs"

Get-ChildItem $logDir -File |
    Where-Object { $_.Name -like "run_pipeline_*.log" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 30 |
    Remove-Item -Force

# Automatically create a timestamped filename
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
Start-Transcript -Path ".\logs\run_pipeline_$stamp.log"

python -m utilities.health_check

if ($LASTEXITCODE -ne 0)
{
    Write-Host "Health checks failed. Exiting pipeline."
    exit 1
}

$day = (Get-Date).DayOfWeek

$localNow = Get-Date
$utcNow   = $localNow.ToUniversalTime()
$utcBucket = $utcNow.Date

Write-Host "Current Day: $day"
Write-Host "Local Time : $localNow"
Write-Host "UTC Time   : $utcNow"
Write-Host "UTC Bucket : $utcBucket"

switch ($day)
{
    "Monday" {
        python -m collectors.save_daily_metrics
    }

    "Tuesday" {
        python -m collectors.save_daily_metrics
    }

    "Wednesday" {
        python -m collectors.save_daily_metrics
    }

    "Thursday" {
        python -m collectors.save_daily_metrics
    }

    "Friday" {
        python -m collectors.save_dividend_history
    }

    "Saturday" {
        python -m collectors.save_free_cash_flow
    }

    "Sunday" {
        python -m analyzers.dividend_safety_analyzer
        python -m analyzers.portfolio_scorecard
    }
}
Stop-Transcript

Write-Host ""
Write-Host "==================================="
Write-Host "PIPELINE COMPLETE"
Write-Host "Finished: $(Get-Date)"
Write-Host "==================================="