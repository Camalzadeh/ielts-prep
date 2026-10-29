# Creates "IELTS Prep" shortcuts on the Desktop and in the Start menu.
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $root "launcher\launch.pyw"
$icon = Join-Path $root "launcher\ielts.ico"

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "IELTS Prep.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "IELTS Prep.lnk")
)
foreach ($path in $targets) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$launcher`""
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "IELTS Prep - local practice app"
    $lnk.Save()
    Write-Output "Created $path"
}
