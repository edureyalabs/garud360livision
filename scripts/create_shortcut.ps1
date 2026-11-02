# scripts/create_shortcut.ps1
# Creates a "Garud 360 Li-Vision" desktop shortcut that launches the app without a console window.
$root = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$icon = Join-Path $root "assets\icon.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Garud 360 Li-Vision.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = $pyw
$sc.Arguments = "-m garud360"
$sc.WorkingDirectory = $root
$sc.IconLocation = $icon
$sc.Description = "Garud 360 Li-Vision"
$sc.Save()
Write-Host "Shortcut created: $lnk"
