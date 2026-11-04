# Tests the installer on another Windows computer, and writes the results to a text file.
# Put this next to PDFDesk-Setup-*.exe and sample.pdf, then run it inside the computer:
#
#   powershell -ExecutionPolicy Bypass -File vm_test.ps1
#
# It installs PDF Desk for the current user if it isn't installed, and leaves it installed so
# you can try it. Add -Uninstall to remove it again at the end. It uses a temporary profile,
# changes no system settings, and needs no administrator rights or internet connection.
param([switch]$Uninstall)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$results = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PDFDesk-Test-Results.txt'
$app = "$env:LOCALAPPDATA\Programs\PDF Desk"
$failures = 0
Set-Content $results "PDF Desk test, $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

function Say($text) { Write-Host $text; Add-Content $results $text }
function Check($label, $passed, $detail) {
    if (-not $passed) { $script:failures++ }
    Say (("{0} {1}" -f $(if ($passed) { 'PASS' } else { 'FAIL' }), $label) + $(if ($detail) { "  ($detail)" } else { '' }))
}

$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$bits = Get-CimInstance Win32_ComputerSystem
Say "Windows: $($os.Caption) build $($os.BuildNumber)"
Say "CPU: $($cpu.Name.Trim()), $($cpu.NumberOfCores) cores, $($cpu.NumberOfLogicalProcessors) threads"
Say "Memory: $([math]::Round($bits.TotalPhysicalMemory / 1GB, 1)) GB"
Say "On a domain: $($bits.PartOfDomain)"
Say "Python on PATH: $([bool](Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' }))"
Say "ffmpeg on PATH: $([bool](Get-Command ffmpeg.exe -ErrorAction SilentlyContinue))"
Say ""

$sample = Join-Path $here 'sample.pdf'
$setup = Get-ChildItem $here -Filter 'PDFDesk-Setup-*.exe' | Select-Object -First 1
if (-not (Test-Path "$app\PDFDesk.exe")) {
    if (-not $setup) { Check 'installer found next to this script' $false; exit 1 }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process $setup.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru -Wait
    Check 'silent install' ($p.ExitCode -eq 0) "exit $($p.ExitCode), $([math]::Round($watch.Elapsed.TotalSeconds)) s"
}
else {
    Say 'Already installed, so testing that copy.'
}
Check 'app installed' (Test-Path "$app\PDFDesk.exe")
Check 'licence installed' (Test-Path "$app\_internal\LICENSE")
Check 'source code installed' ([bool](Get-ChildItem "$app\source" -Filter '*.zip' -ErrorAction SilentlyContinue))
Check 'Start menu shortcut' (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\PDF Desk\PDF Desk.lnk")
Check 'Open With entry' ((Get-Item 'HKCU:\Software\Classes\.pdf\OpenWithProgids' -ErrorAction SilentlyContinue).GetValueNames() -contains 'PDFDesk.pdf')
if (-not (Test-Path "$app\PDFDesk.exe")) { Say "Results are in $results"; exit 1 }

# A profile of its own, so testing doesn't touch real settings.
$env:PDFDESK_HOME = Join-Path $env:TEMP "pdfdesk-vm-test-$(Get-Random)"
New-Item -ItemType Directory -Force $env:PDFDESK_HOME | Out-Null

Say ''
Say 'Running the self-check: real voices, MP3 export and OCR, muted...'
$check = Join-Path $env:TEMP "pdfdesk-self-check-$(Get-Random).txt"
$watch = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process "$app\PDFDesk.exe" -ArgumentList '--self-check', "`"$check`"" -PassThru
$done = $p.WaitForExit(400000)
Check 'self-check finished' ($done -and $p.ExitCode -eq 0) "exit $(if ($done) { $p.ExitCode } else { 'timed out' }), $([math]::Round($watch.Elapsed.TotalSeconds)) s"
if (-not $done) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Get-Content $check -ErrorAction SilentlyContinue | ForEach-Object { Say "   $_" }

Say ''
if (Test-Path $sample) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process "$app\PDFDesk.exe" -ArgumentList "`"$sample`"" -PassThru
    $title = ''
    while ($watch.Elapsed.TotalSeconds -lt 60 -and $title -notmatch 'sample') { Start-Sleep -Milliseconds 100; $p.Refresh(); $title = $p.MainWindowTitle }
    Check 'opens a PDF from the command Windows uses' ($title -match 'sample') "[$title] after $([math]::Round($watch.Elapsed.TotalSeconds, 1)) s"
    Start-Sleep -Seconds 2
    $p.Refresh()
    Say "Memory with a PDF open: $([math]::Round($p.WorkingSet64 / 1MB)) MB"
    $second = Start-Process "$app\PDFDesk.exe" -ArgumentList "`"$sample`"" -PassThru
    Check 'second launch hands over to the first' ($second.WaitForExit(20000) -and $second.ExitCode -eq 0)
    [void]$p.CloseMainWindow()
    Check 'closes cleanly' ($p.WaitForExit(20000))
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}
else {
    Check 'sample.pdf found next to this script' $false
}
$log = Join-Path $env:PDFDESK_HOME 'logs\pdfdesk.log'
$problems = @(Get-Content $log -ErrorAction SilentlyContinue | Where-Object { $_ -match ' (ERROR|CRITICAL) ' })
Check 'no errors in the log' ($problems.Count -eq 0) "$($problems.Count) errors"
$problems | Select-Object -First 10 | ForEach-Object { Say "   $_" }
Remove-Item Env:PDFDESK_HOME
Remove-Item $check -ErrorAction SilentlyContinue

if ($Uninstall) {
    Say ''
    $p = Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru -Wait
    Start-Sleep -Seconds 5
    Check 'silent uninstall' ($p.ExitCode -eq 0)
    Check 'app folder removed' (-not (Test-Path $app))
    Check 'Open With entry removed' (-not ((Get-Item 'HKCU:\Software\Classes\.pdf\OpenWithProgids' -ErrorAction SilentlyContinue).GetValueNames() -contains 'PDFDesk.pdf'))
}

Say ''
Say $(if ($failures) { "$failures CHECKS FAILED" } else { 'ALL CHECKS PASSED' })
Say "Results are in $results"
