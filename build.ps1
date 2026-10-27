param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Falta .venv. Prepará el entorno según README.md.'
}
if (-not $SkipTests) {
    & $python -m unittest discover -s tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas.' }
}
& $python tools\render_icon.py
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el icono.' }
& $python -m PyInstaller --noconfirm --clean CS2Stats.spec
if ($LASTEXITCODE -ne 0) { throw 'Falló el empaquetado.' }
$exe = Join-Path $PSScriptRoot 'dist\CS2Stats\CS2Stats.exe'

# Acceso directo en el escritorio.
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'CS2 Stats.lnk'))
$link.TargetPath = $exe
$link.WorkingDirectory = Split-Path $exe
$link.IconLocation = "$exe,0"
$link.Description = 'Tus partidas de CS2, tus números y qué practicar'
$link.Save()
Write-Output $exe
