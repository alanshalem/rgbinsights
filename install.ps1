# RGB Semaforo - instalador de un click para Windows.
#
# Para el cliente: bajas ESTE archivo, click derecho -> "Ejecutar con PowerShell".
# La primera vez clona el proyecto desde GitHub; despues lo actualiza. Al final
# levanta la app (start.ps1). No necesitas saber programar.
#
# Para actualizar mas adelante tambien podes simplemente correr start.ps1:
# arranca haciendo 'git pull' solo.

$ErrorActionPreference = 'Stop'
$REPO = 'https://github.com/alanshalem/rgbinsights.git'

function Info($m) { Write-Host "  $m" -ForegroundColor Gray }
function Ok($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Step($m) { Write-Host "`n=> $m" -ForegroundColor Cyan }
function Die($m) {
  Write-Host "`nX  $m" -ForegroundColor Red
  Read-Host "`n(Enter para cerrar)"
  exit 1
}

Write-Host "RGB Semaforo - instalador" -ForegroundColor Magenta

# ---------------------------------------------------------------- Git
Step "Chequeando Git"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Info "No hay Git. Intento instalarlo con winget..."
  try {
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
  } catch { }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Die "No pude instalar Git. Instalalo a mano desde https://git-scm.com/download/win y volve a correr esto."
  }
}
Ok "Git disponible"

# ---------------------------------------------------------------- Clonar / actualizar
# Si este instalador ya esta dentro del repo, lo usamos tal cual; si no, clonamos
# en una subcarpeta 'rgbinsights' al lado del instalador.
if (Test-Path "$PSScriptRoot\.git") {
  $dir = $PSScriptRoot
  Step "Actualizando el proyecto (git pull)"
  git -C $dir pull --ff-only
} else {
  $dir = Join-Path $PSScriptRoot 'rgbinsights'
  if (Test-Path "$dir\.git") {
    Step "Actualizando el proyecto (git pull)"
    git -C $dir pull --ff-only
  } else {
    Step "Descargando el proyecto (git clone)"
    git clone $REPO $dir
  }
}
Ok "Proyecto en: $dir"

# ---------------------------------------------------------------- Arrancar
$start = Join-Path $dir 'start.ps1'
if (-not (Test-Path $start)) { Die "No encontre start.ps1 en $dir." }
Step "Levantando la app..."
& powershell -ExecutionPolicy Bypass -File $start
