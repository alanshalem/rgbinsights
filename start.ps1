# RGB Semáforo — launcher para Windows.
#
# Chequea requisitos, instala lo que falte y levanta backend + frontend.
# Uso:
#   Click derecho -> "Ejecutar con PowerShell"
#   o en una terminal:  powershell -ExecutionPolicy Bypass -File start.ps1
#
# No necesitás saber programar: si falta algo, te dice qué instalar.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$MIN_PY = [version]'3.12'
$MIN_NODE = 20

function Info($m) { Write-Host "  $m" -ForegroundColor Gray }
function Ok($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Step($m) { Write-Host "`n=> $m" -ForegroundColor Cyan }
function Fail($m) {
  Write-Host "`nX  $m" -ForegroundColor Red
  Write-Host "`nArreglá eso y volvé a correr start.ps1." -ForegroundColor Yellow
  Read-Host "`n(Enter para cerrar)"
  exit 1
}

Write-Host "RGB Semáforo — arranque" -ForegroundColor Magenta

# ---------------------------------------------------------------- Python
Step "Chequeando Python (>= $MIN_PY)"
$python = $null
foreach ($cand in @('python', 'py -3')) {
  try {
    $exe, $arg = $cand.Split(' ')
    $ver = & $exe $arg --version 2>&1
    if ($ver -match '(\d+)\.(\d+)\.(\d+)') {
      $v = [version]"$($Matches[1]).$($Matches[2])"
      if ($v -ge $MIN_PY) { $python = $cand; Ok "Python $v ($cand)"; break }
      else { Info "Encontrado Python $v pero necesito >= $MIN_PY" }
    }
  } catch { }
}
if (-not $python) {
  Fail "No hay Python >= $MIN_PY. Instalalo desde https://www.python.org/downloads/ (tildá 'Add Python to PATH')."
}
$pyExe, $pyArg = $python.Split(' ')

# ---------------------------------------------------------------- Node
Step "Chequeando Node.js (>= $MIN_NODE) y npm"
try { $nodeVer = (node -v) 2>&1 } catch { $nodeVer = '' }
if ($nodeVer -notmatch 'v(\d+)\.') {
  Fail "No hay Node.js. Instalá la version LTS desde https://nodejs.org/"
}
$nodeMajor = [int]$Matches[1]
if ($nodeMajor -lt $MIN_NODE) {
  Fail "Node.js $nodeVer es viejo. Necesito >= $MIN_NODE. Actualizá desde https://nodejs.org/"
}
try { $npmVer = (npm -v) 2>&1 } catch { Fail "npm no esta disponible (viene con Node.js)." }
Ok "Node $nodeVer, npm $npmVer"

# ---------------------------------------------------------------- Backend setup
Step "Preparando backend"
Set-Location "$root\backend"
$venvPy = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Info "Creando entorno virtual (.venv)…"
  & $pyExe $pyArg -m venv .venv
}
Info "Instalando dependencias de Python…"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r requirements.txt
if (-not (Test-Path "$root\backend\.env")) {
  Copy-Item "$root\backend\.env.example" "$root\backend\.env"
  Info ".env creado desde .env.example (modo demo con datos de ejemplo)."
}
Ok "Backend listo"

# ---------------------------------------------------------------- Frontend setup
Step "Preparando frontend"
Set-Location "$root\frontend"
if (-not (Test-Path "$root\frontend\node_modules")) {
  Info "Instalando dependencias de Node (npm install)…"
  npm install --no-fund --no-audit
}
Ok "Frontend listo"

# ---------------------------------------------------------------- Arrancar backend
Step "Levantando backend en http://127.0.0.1:8000"
Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root\backend'; & '$venvPy' -m uvicorn app.main:app --reload --port 8000"
)

Info "Esperando a que el backend responda…"
$ready = $false
foreach ($i in 1..30) {
  try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2 | Out-Null
    $ready = $true; break
  } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { Fail "El backend no respondio a tiempo. Fijate la ventana del backend por errores." }
Ok "Backend arriba"

# ---------------------------------------------------------------- Generar cliente + frontend
Step "Generando cliente tipado desde el backend"
npm run gen:api

Step "Levantando frontend en http://localhost:5173"
Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command', "cd '$root\frontend'; npm run dev"
)

Write-Host "`n----------------------------------------------" -ForegroundColor Magenta
Ok "Todo levantado."
Info "Frontend:  http://localhost:5173"
Info "Backend:   http://127.0.0.1:8000  (docs en /docs)"
Info "Se abrieron dos ventanas. Cerralas para frenar la app."
Read-Host "`n(Enter para cerrar esta ventana)"
