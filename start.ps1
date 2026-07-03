# Levanta backend y frontend en dos ventanas (Windows PowerShell).
# Uso:  ./start.ps1
# Requiere haber corrido la instalación una vez (ver README).

$root = $PSScriptRoot

Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root\backend'; .venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8000"
)

Start-Sleep -Seconds 2

Start-Process powershell -ArgumentList @(
  '-NoExit', '-Command',
  "cd '$root\frontend'; npm run dev"
)

Write-Host "Backend en http://127.0.0.1:8000  ·  Frontend en http://localhost:5173"
