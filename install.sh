#!/usr/bin/env bash
# RGB Semáforo — instalador de un click para macOS y Linux.
#
# Para el cliente: bajás ESTE archivo y corrés:
#   bash install.sh
# La primera vez clona el proyecto desde GitHub; después lo actualiza. Al final
# levanta la app (start.sh). No necesitás saber programar.
#
# Para actualizar más adelante también podés correr ./start.sh directamente:
# arranca haciendo 'git pull' solo.

set -euo pipefail
REPO='https://github.com/alanshalem/rgbinsights.git'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -t 1 ]; then
  C_GRAY='\033[90m'; C_GREEN='\033[32m'; C_CYAN='\033[36m'
  C_RED='\033[31m'; C_MAGENTA='\033[35m'; C_OFF='\033[0m'
else
  C_GRAY=''; C_GREEN=''; C_CYAN=''; C_RED=''; C_MAGENTA=''; C_OFF=''
fi
info() { printf "${C_GRAY}  %s${C_OFF}\n" "$1"; }
ok()   { printf "${C_GREEN}OK  %s${C_OFF}\n" "$1"; }
step() { printf "\n${C_CYAN}=> %s${C_OFF}\n" "$1"; }
die()  { printf "\n${C_RED}X  %s${C_OFF}\n" "$1"; exit 1; }

printf "${C_MAGENTA}RGB Semáforo — instalador${C_OFF}\n"

# ---------------------------------------------------------------- Git
step "Chequeando Git"
if ! command -v git >/dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin) die "No hay Git. Instalalo con:  xcode-select --install   (o brew install git) y reintentá." ;;
    *)      die "No hay Git. Ej. Ubuntu/Debian:  sudo apt install git   y reintentá." ;;
  esac
fi
ok "Git disponible"

# ---------------------------------------------------------------- Clonar / actualizar
if [ -d "$HERE/.git" ]; then
  DIR="$HERE"
  step "Actualizando el proyecto (git pull)"; git -C "$DIR" pull --ff-only
else
  DIR="$HERE/rgbinsights"
  if [ -d "$DIR/.git" ]; then
    step "Actualizando el proyecto (git pull)"; git -C "$DIR" pull --ff-only
  else
    step "Descargando el proyecto (git clone)"; git clone "$REPO" "$DIR"
  fi
fi
ok "Proyecto en: $DIR"

# ---------------------------------------------------------------- Arrancar
[ -f "$DIR/start.sh" ] || die "No encontré start.sh en $DIR."
chmod +x "$DIR/start.sh" 2>/dev/null || true
step "Levantando la app…"
exec bash "$DIR/start.sh"
