# RGB Semaforo - launcher para Windows.
#
# Chequea requisitos, se actualiza desde el repo, instala lo que falte y
# levanta backend + frontend. Al apretar Enter, cierra TODO (las dos ventanas
# que abrio) y te deja en la carpeta del proyecto.
#
# Uso:
#   Click derecho -> "Ejecutar con PowerShell"
#   o en una terminal:  powershell -ExecutionPolicy Bypass -File start.ps1
#
# No necesitas saber programar: si falta algo, te dice que instalar.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$MIN_PY = [version]'3.12'
$MIN_NODE = 20
$updated = $false

function Info($m) { Write-Host "  $m" -ForegroundColor Gray }
function Ok($m) { Write-Host "OK  $m" -ForegroundColor Green }
function Step($m) { Write-Host "`n=> $m" -ForegroundColor Cyan }
function Fail($m) {
  Write-Host "`nX  $m" -ForegroundColor Red
  Write-Host "`nArregla eso y volve a correr start.ps1." -ForegroundColor Yellow
  Set-Location $root
  Read-Host "`n(Enter para cerrar)"
  exit 1
}

Write-Host "RGB Semaforo - arranque" -ForegroundColor Magenta

# ---------------------------------------------------------------- Auto-update
# Traer la ultima version del repo. Si no hay git o no hay 'origin', se saltea
# sin romper: seguis con el codigo que ya tenes.
Step "Buscando actualizaciones del codigo"
if ((Get-Command git -ErrorAction SilentlyContinue) -and (Test-Path "$root\.git")) {
  try {
    $before = (git -C $root rev-parse HEAD 2>$null)
    git -C $root pull --ff-only 2>&1 | ForEach-Object { Info $_ }
    $after = (git -C $root rev-parse HEAD 2>$null)
    if ($before -and $after -and ($before -ne $after)) {
      $updated = $true
      Ok "Codigo actualizado a la ultima version."
    } else {
      Ok "Ya estabas al dia."
    }
  } catch {
    Info "No se pudo actualizar (seguimos con la version actual)."
  }
} else {
  Info "Sin git o sin repo remoto - salteo la actualizacion."
}

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
  Fail "No hay Python >= $MIN_PY. Instalalo desde https://www.python.org/downloads/ (tilda 'Add Python to PATH')."
}
$pyExe, $pyArg = $python.Split(' ')

# ---------------------------------------------------------------- Node
Step "Chequeando Node.js (>= $MIN_NODE) y npm"
try { $nodeVer = (node -v) 2>&1 } catch { $nodeVer = '' }
if ($nodeVer -notmatch 'v(\d+)\.') {
  Fail "No hay Node.js. Instala la version LTS desde https://nodejs.org/"
}
$nodeMajor = [int]$Matches[1]
if ($nodeMajor -lt $MIN_NODE) {
  Fail "Node.js $nodeVer es viejo. Necesito >= $MIN_NODE. Actualiza desde https://nodejs.org/"
}
try { $npmVer = (npm -v) 2>&1 } catch { Fail "npm no esta disponible (viene con Node.js)." }
Ok "Node $nodeVer, npm $npmVer"

# ---------------------------------------------------------------- Backend setup
Step "Preparando backend"
Set-Location "$root\backend"
$venvPy = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Info "Creando entorno virtual (.venv)..."
  & $pyExe $pyArg -m venv .venv
}
Info "Instalando dependencias de Python..."
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
# Reinstalar si faltan deps o si el auto-update trajo cambios (package.json nuevo).
if ((-not (Test-Path "$root\frontend\node_modules")) -or $updated) {
  Info "Instalando dependencias de Node (npm install)..."
  npm install --no-fund --no-audit
}
Ok "Frontend listo"

# ---------------------------------------------------------------- Arrancar backend
Step "Levantando backend en http://127.0.0.1:8000"
$backendProc = Start-Process powershell -PassThru -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root\backend'; & '$venvPy' -m uvicorn app.main:app --port 8000"
)

Info "Esperando a que el backend responda..."
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
$frontendProc = Start-Process powershell -PassThru -ArgumentList @(
  '-NoExit', '-Command', "cd '$root\frontend'; npm run dev"
)

Write-Host "`n----------------------------------------------" -ForegroundColor Magenta
Ok "Todo levantado."
Info "Frontend:  http://localhost:5173"
Info "Backend:   http://127.0.0.1:8000  (docs en /docs)"
Info "Enter aca abajo cierra TODO (backend, frontend y sus ventanas)."
Set-Location $root
Read-Host "`n(Enter para cerrar todo)"

# ---------------------------------------------------------------- Cierre
Step "Cerrando la app..."
foreach ($p in @($backendProc, $frontendProc)) {
  if ($p -and -not $p.HasExited) {
    # /T mata tambien los hijos (uvicorn / node), /F fuerza el cierre.
    taskkill /PID $p.Id /T /F 2>$null | Out-Null
  }
}
Set-Location $root
Ok "App frenada. Listo."
