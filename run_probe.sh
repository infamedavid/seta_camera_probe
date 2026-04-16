#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/seta_camera_probe.py"

is_debian_like() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    local id_like="${ID_LIKE:-}"
    local id="${ID:-}"
    [[ "${id}" == "ubuntu" || "${id}" == "debian" || "${id_like}" == *debian* ]]
    return
  fi
  return 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

print_missing_help() {
  echo
  echo "Faltan dependencias del sistema."
  echo "En Ubuntu/Debian normalmente puedes instalarlas con:"
  echo "  sudo apt-get update"
  echo "  sudo apt-get install -y python3 gphoto2 ffmpeg"
  echo
}

install_missing_deps() {
  local packages=("$@")

  if [[ ${#packages[@]} -eq 0 ]]; then
    return 0
  fi

  if ! is_debian_like; then
    echo "Auto-instalación no soportada en esta distro."
    print_missing_help
    return 1
  fi

  echo
  echo "Faltan estas dependencias: ${packages[*]}"
  read -r -p "¿Quieres instalarlas ahora con sudo? [y/N] " answer

  case "${answer}" in
    y|Y|yes|YES|s|S|si|SI)
      sudo apt-get update
      sudo apt-get install -y "${packages[@]}"
      ;;
    *)
      echo "Instalación cancelada por el usuario."
      print_missing_help
      return 1
      ;;
  esac
}

main() {
  local missing_packages=()

  if ! have_cmd python3; then
    missing_packages+=("python3")
  fi

  if ! have_cmd gphoto2; then
    missing_packages+=("gphoto2")
  fi

  if ! have_cmd ffplay; then
    # ffplay viene dentro del paquete ffmpeg en Ubuntu/Debian
    missing_packages+=("ffmpeg")
  fi

  if [[ ${#missing_packages[@]} -gt 0 ]]; then
    install_missing_deps "${missing_packages[@]}"
  fi

  if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
    echo "No se encontró el script Python:"
    echo "  ${PYTHON_SCRIPT}"
    exit 1
  fi

  echo
  echo "Iniciando SETA camera probe..."
  exec python3 "${PYTHON_SCRIPT}" "$@"
}

main "$@"
