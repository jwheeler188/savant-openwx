#!/bin/bash
# zsh is the macOS default shell: if started with "zsh file" or "sh file", relaunch in bash
[ -n "${BASH_VERSION:-}" ] || exec /bin/bash "$0" "$@"
# Savant OpenWx - macOS uninstaller
#
#   sudo ./uninstall.sh                 remove everything install.sh added (asks to confirm)
#   sudo ./uninstall.sh --keep-config   save config.json + location to ~/OpenWx-backup-<date> first
#   sudo ./uninstall.sh --yes           don't ask
#   sudo ./uninstall.sh --dir /path     install folder, if not ~/OpenWx
#
# Reverses only what install.sh recorded in .install-manifest:
#   launchd service, /usr/local/bin/openwx, the firewall exception (only if install added it),
#   /usr/local/bin (only if install created it), and the install folder.
set -uo pipefail

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*"; }
fail() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

KEEP=0; YES=0; DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --keep-config) KEEP=1; shift ;;
    --yes|-y)      YES=1; shift ;;
    --dir)         DIR="$2"; shift 2 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

[ "$(uname)" = "Darwin" ] || fail "this uninstaller is for macOS"
[ "$(id -u)" -eq 0 ] || fail "run with sudo: sudo $0"

# ---- find the install --------------------------------------------------------
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -z "$DIR" ]; then
  if [ -f "$HERE/.install-manifest" ]; then
    DIR="$HERE"                                   # running the copy inside the install folder
  else
    U="${SUDO_USER:-${USER:-$(id -un)}}"
    DIR="$(dscl . -read "/Users/$U" NFSHomeDirectory 2>/dev/null | awk '{print $2}')/OpenWx"
  fi
fi

LABEL="org.openwx.bridge"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"
DEST="$DIR"; RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"; PYTHON=""; FW_ADDED=0; CREATED_BIN=0
if [ -f "$DIR/.install-manifest" ]; then
  # bash 3.2 (macOS /bin/bash) can't source <(...), so eval the known keys
  eval "$(grep -E '^(LABEL|PLIST|DEST|RUN_USER|PYTHON|FW_ADDED|CREATED_BIN)=[^;&|$\`]*$' "$DIR/.install-manifest")"
else
  warn "no install record in $DIR - removing the service and folder only; any firewall entry is left alone"
fi

# safety: only ever delete a folder named OpenWx
case "$DEST" in
  */OpenWx) ;;
  *) fail "refusing to delete '$DEST' (expected a folder named OpenWx). Use --dir." ;;
esac

echo
echo "This will remove:"
[ -f "$PLIST" ] && echo "  - launchd service $LABEL (stops the bridge)"
[ -L /usr/local/bin/openwx ] && echo "  - /usr/local/bin/openwx"
[ "$FW_ADDED" = "1" ] && echo "  - firewall exception for $PYTHON"
[ -d "$DEST" ] && echo "  - $DEST$( [ "$KEEP" = 1 ] && echo ' (config and location backed up first)')"
echo
if [ "$YES" -ne 1 ]; then
  read -r -p "Continue? [y/N] " a
  case "$a" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 0 ;; esac
fi

# ---- stop & remove the service ----------------------------------------------
if launchctl print "system/$LABEL" >/dev/null 2>&1; then
  say "Stopping the bridge"
  launchctl bootout "system/$LABEL" 2>/dev/null || true   # SIGTERM, clean shutdown
  for _ in $(seq 1 20); do pgrep -f "$DEST/openwx_bridge.py" >/dev/null || break; sleep 1; done
  pgrep -f "$DEST/openwx_bridge.py" >/dev/null && { warn "still running - killing"; pkill -9 -f "$DEST/openwx_bridge.py"; }
fi
launchctl enable "system/$LABEL" 2>/dev/null || true       # clear any 'disabled' override
if [ -f "$PLIST" ]; then
  say "Removing $PLIST"
  rm -f "$PLIST"
fi

# ---- command shortcut --------------------------------------------------------
if [ -L /usr/local/bin/openwx ]; then
  say "Removing /usr/local/bin/openwx"
  rm -f /usr/local/bin/openwx
fi
if [ "$CREATED_BIN" = "1" ] && [ -d /usr/local/bin ] && [ -z "$(ls -A /usr/local/bin)" ]; then
  rmdir /usr/local/bin
fi

# ---- firewall ----------------------------------------------------------------
FW=/usr/libexec/ApplicationFirewall/socketfilterfw
if [ "$FW_ADDED" = "1" ] && [ -n "$PYTHON" ] && [ -x "$FW" ]; then
  say "Removing firewall exception for Python"
  "$FW" --remove "$PYTHON" >/dev/null 2>&1 || warn "could not remove firewall entry; remove Python in Firewall Options manually"
fi

# ---- files -------------------------------------------------------------------
if [ -d "$DEST" ]; then
  if [ "$KEEP" = "1" ]; then
    BK="$(dirname "$DEST")/OpenWx-backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BK"
    cp -p "$DEST/config.json" "$BK/" 2>/dev/null || true
    cp -p "$DEST/wx_state.json" "$BK/" 2>/dev/null || true
    chown -R "$RUN_USER" "$BK"
    say "Saved config.json and location to $BK"
  fi
  say "Removing $DEST"
  rm -rf "$DEST"
fi

say "Uninstalled. The Savant profile will show the bridge as offline (SYS_ONLINE = 0);"
echo "    remove the component from the Blueprint layout if you're not reinstalling."
