#!/usr/bin/env bash
# RGB Semáforo — launcher para macOS y Linux.
#
# Chequea requisitos, instala lo que falte y levanta backend + frontend.
# Uso:
#   chmod +x start.sh        (una sola vez)
#   ./start.sh
#
# No necesitás saber programar: si falta algo, te dice qué instalar.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIN_PY_MAJOR=3
MIN_PY_MINOR=12
MIN_NODE=20

# Colores (si la terminal los soporta)
if [ -t 1 ]; then
  C_GRAY='\033[90m'; C_GREEN='\033[32m'; C_CYAN='\033[36m'
  C_RED='\033[31m'; C_YELLOW='\033[33m'; C_MAGENTA='\033[35m'; C_OFF='\033[0m'
else
  C_GRAY=''; C_GREEN=''; C_CYAN=''; C_RED=''; C_YELLOW=''; C_MAGENTA=''; C_OFF=''
fi
info() { printf "${C_GRAY}  %s${C_OFF}\n" "$1"; }
ok()   { printf "${C_GREEN}OK  %s${C_OFF}\n" "$1"; }
step() { printf "\n${C_CYAN}=> %s${C_OFF}\n" "$1"; }
fail() {
  printf "\n${C_RED}X  %s${C_OFF}\n" "$1"
  printf "${C_YELLOW}\nArreglá eso y volvé a correr ./start.sh${C_OFF}\n"
  exit 1
}

os_name() { case "$(uname -s)" in Darwin) echo macOS;; Linux) echo Linux;; *) echo "$(uname -s)";; esac; }

printf "${C_MAGENTA}RGB Semáforo — arranque (%s)${C_OFF}\n" "$(os_name)"

# ---------------------------------------------------------------- Python
step "Chequeando Python (>= ${MIN_PY_MAJOR}.${MIN_PY_MINOR})"
PYTHON=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (${MIN_PY_MAJOR}, ${MIN_PY_MINOR}) else 1)" 2>/dev/null; then
      PYTHON="$cand"
      ok "Python $("$cand" -c 'import platform; print(platform.python_version())') ($cand)"
      break
    else
      info "Encontrado $("$cand" --version 2>&1) pero necesito >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}"
    fi
  fi
done
if [ -z "$PYTHON" ]; then
  if [ "$(os_name)" = "macOS" ]; then
    fail "No hay Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}. Instalalo con:  brew install python@3.12   (o desde https://www.python.org/downloads/)"
  else
    fail "No hay Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}. Ej. Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
  fi
fi

# ---------------------------------------------------------------- Node
step "Chequeando Node.js (>= ${MIN_NODE}) y npm"
if ! command -v node >/dev/null 2>&1; then
  fail "No hay Node.js. Instalá la version LTS desde https://nodejs.org/ (o con nvm / brew / apt)."
fi
NODE_VER="$(node -v)"
NODE_MAJOR="$(printf '%s' "$NODE_VER" | sed -E 's/^v([0-9]+).*/\1/')"
if [ "$NODE_MAJOR" -lt "$MIN_NODE" ]; then
  fail "Node.js $NODE_VER es viejo. Necesito >= ${MIN_NODE}. Actualizá desde https://nodejs.org/"
fi
command -v npm >/dev/null 2>&1 || fail "npm no esta disponible (viene con Node.js)."
ok "Node $NODE_VER, npm $(npm -v)"

# ---------------------------------------------------------------- Backend setup
step "Preparando backend"
cd "$ROOT/backend"
VENV_PY="$ROOT/backend/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  info "Creando entorno virtual (.venv)…"
  "$PYTHON" -m venv .venv
fi
info "Instalando dependencias de Python…"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements.txt
if [ ! -f "$ROOT/backend/.env" ]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  info ".env creado desde .env.example (modo demo con datos de ejemplo)."
fi
ok "Backend listo"

# ---------------------------------------------------------------- Frontend setup
step "Preparando frontend"
cd "$ROOT/frontend"
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  info "Instalando dependencias de Node (npm install)…"
  npm install --no-fund --no-audit
fi
ok "Frontend listo"

# ---------------------------------------------------------------- Arrancar
# El backend corre en segundo plano; el frontend en primer plano.
# Al cortar con Ctrl+C, matamos el backend también.
BACKEND_PID=""
cleanup() {
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

step "Levantando backend en http://127.0.0.1:8000"
( cd "$ROOT/backend" && "$VENV_PY" -m uvicorn app.main:app --port 8000 ) &
BACKEND_PID=$!

info "Esperando a que el backend responda…"
ready=0
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = "1" ] || fail "El backend no respondio a tiempo. Fijate arriba si hay errores."
ok "Backend arriba"

step "Generando cliente tipado desde el backend"
( cd "$ROOT/frontend" && npm run gen:api )

printf "\n${C_MAGENTA}----------------------------------------------${C_OFF}\n"
ok "Todo listo. Levantando frontend…"
info "Frontend:  http://localhost:5173"
info "Backend:   http://127.0.0.1:8000  (docs en /docs)"
info "Cortá con Ctrl+C para frenar todo."
printf "\n"

# Frontend en primer plano: cuando lo cortás, el trap frena el backend.
cd "$ROOT/frontend"
npm run dev
