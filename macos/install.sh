#!/bin/bash
# zsh is the macOS default shell: if started with "zsh file" or "sh file", relaunch in bash
[ -n "${BASH_VERSION:-}" ] || exec /bin/bash "$0" "$@"
# Savant OpenWx - macOS installer (Savant Mac mini Pro host)
#
#   sudo ./install.sh                 install or upgrade, run as the current user
#   sudo ./install.sh --user RPM      run the service as a specific macOS user
#
# Upgrades keep the existing config.json and saved location.
set -euo pipefail
trap 'printf "\033[31mERROR:\033[0m install stopped at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

LABEL="org.openwx.bridge"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$HERE/../bridge" && pwd)"

RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"
while [ $# -gt 0 ]; do
  case "$1" in
    --user) RUN_USER="$2"; shift 2 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "this installer is for macOS"
[ "$(id -u)" -eq 0 ] || fail "run with sudo: sudo $0"
id "$RUN_USER" >/dev/null 2>&1 || fail "user '$RUN_USER' does not exist"
[ "$RUN_USER" != "root" ] || fail "refusing to run the service as root; use --user <name>"

USER_HOME="$(dscl . -read "/Users/$RUN_USER" NFSHomeDirectory | awk '{print $2}')"
DEST="$USER_HOME/OpenWx"

# ---- Python ----------------------------------------------------------------
say "Checking Python"
PY=""
for c in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if [ -x "$c" ] && sudo -u "$RUN_USER" "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,6) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.6+ not found. On macOS 11+ run: xcode-select --install"
# /usr/bin/python3 is Apple's shim; resolve the real binary for launchd and the firewall
REAL_PY="$(sudo -u "$RUN_USER" "$PY" -c 'import sys; print(sys.executable)')"
echo "    $("$REAL_PY" --version) at $REAL_PY"
[ -x /usr/bin/curl ] || fail "/usr/bin/curl missing"

# ---- Ports -----------------------------------------------------------------
CFG_SRC="$SRC/config.json"
[ -f "$DEST/config.json" ] && CFG_SRC="$DEST/config.json"
TCP_PORT="$("$REAL_PY" -c "import json;print(json.load(open('$CFG_SRC')).get('tcp_port',2350))")"
HTTP_PORT="$("$REAL_PY" -c "import json;print(json.load(open('$CFG_SRC')).get('http_port',8642))")"

# stop an existing install first so its own ports don't count as conflicts
if launchctl print "system/$LABEL" >/dev/null 2>&1; then
  say "Stopping existing service"
  launchctl bootout "system/$LABEL" 2>/dev/null || true
  for _ in $(seq 1 20); do   # wait for the old bridge to release its ports
    lsof -nP -iTCP:"$TCP_PORT" -sTCP:LISTEN >/dev/null 2>&1 || lsof -nP -iTCP:"$HTTP_PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
fi

say "Checking ports $TCP_PORT (Savant) and $HTTP_PORT (dashboard)"
for p in "$TCP_PORT" "$HTTP_PORT"; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    lsof -nP -iTCP:"$p" -sTCP:LISTEN
    fail "port $p is already in use. Change tcp_port/http_port in config.json and rerun."
  fi
done

# ---- Files -----------------------------------------------------------------
ver() { if [ -f "$1" ]; then sed -n 's/^VERSION = "\(.*\)"/\1/p' "$1" | head -1; fi; return 0; }
OLD_VER="$(ver "$DEST/openwx_bridge.py")"
NEW_VER="$(ver "$SRC/openwx_bridge.py")"
say "Installing bridge v${NEW_VER:-?} to $DEST${OLD_VER:+ (replacing v$OLD_VER)}"
echo "    from $SRC"
mkdir -p "$DEST/logs"
cp "$SRC/openwx_bridge.py" "$SRC/dashboard.html" "$DEST/"
cp "$HERE/openwx" "$DEST/"
if [ -f "$DEST/config.json" ]; then
  echo "    keeping existing config.json"
else
  # restore from the newest uninstall --keep-config backup, if there is one
  BK="$(ls -1d "$(dirname "$DEST")"/OpenWx-backup-* 2>/dev/null | sort | tail -1 || true)"
  if [ -n "$BK" ] && [ -f "$BK/config.json" ]; then
    cp -p "$BK/config.json" "$DEST/"
    [ -f "$BK/wx_state.json" ] && cp -p "$BK/wx_state.json" "$DEST/"
    echo "    restored config.json and saved location from $BK"
  else
    cp "$SRC/config.json" "$DEST/"
    echo "    new config.json - edit default_location and contact_email: $DEST/config.json"
  fi
fi
chown -R "$RUN_USER" "$DEST"
chmod 755 "$DEST/openwx" "$DEST/openwx_bridge.py"
CREATED_BIN=0
[ -d /usr/local/bin ] || { mkdir -p /usr/local/bin; CREATED_BIN=1; }
ln -sf "$DEST/openwx" /usr/local/bin/openwx
cp "$HERE/uninstall.sh" "$DEST/"
chmod 755 "$DEST/uninstall.sh"

# ---- launchd ---------------------------------------------------------------
say "Writing $PLIST"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REAL_PY</string>
    <string>$DEST/openwx_bridge.py</string>
    <string>-c</string><string>$DEST/config.json</string>
    <string>-l</string><string>$DEST/logs/bridge.log</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>UserName</key><string>$RUN_USER</string>
  <key>RunAtLoad</key><true/>
  <!-- restart after a crash or the memory watchdog (exit 3); a clean stop (exit 0) stays stopped -->
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ExitTimeOut</key><integer>15</integer>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$DEST/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$DEST/logs/launchd.log</string>
</dict>
</plist>
EOF
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
plutil -lint "$PLIST" >/dev/null || fail "plist failed validation"

# ---- Firewall --------------------------------------------------------------
FW=/usr/libexec/ApplicationFirewall/socketfilterfw
FW_ADDED=0
# keep the record from a previous install so an upgrade doesn't forget an exception it added
if [ -f "$DEST/.install-manifest" ] && grep -q '^FW_ADDED=1' "$DEST/.install-manifest"; then FW_ADDED=1; fi
if [ -x "$FW" ] && "$FW" --getglobalstate | grep -qi "enabled"; then
  if "$FW" --listapps 2>/dev/null | grep -qF "$REAL_PY"; then
    echo "    Python already has a firewall entry - leaving it as is"
  else
    say "macOS firewall is on - allowing incoming connections for Python"
    "$FW" --add "$REAL_PY" >/dev/null || true
    "$FW" --unblockapp "$REAL_PY" >/dev/null || true
    FW_ADDED=1
  fi
fi

# record exactly what this install changed, for uninstall.sh
cat > "$DEST/.install-manifest" <<MANIFEST
# written by install.sh $(date '+%Y-%m-%d %H:%M')
LABEL=$LABEL
PLIST=$PLIST
DEST=$DEST
RUN_USER=$RUN_USER
PYTHON=$REAL_PY
FW_ADDED=$FW_ADDED
CREATED_BIN=$CREATED_BIN
MANIFEST
chown "$RUN_USER" "$DEST/.install-manifest"

# confirm the new files actually landed
GOT_VER="$(ver "$DEST/openwx_bridge.py")"
[ "$GOT_VER" = "$NEW_VER" ] || fail "copy failed: $DEST has v$GOT_VER, expected v$NEW_VER"

# ---- Start & verify --------------------------------------------------------
say "Starting service"
launchctl enable "system/$LABEL" 2>/dev/null || true
launchctl bootstrap system "$PLIST"

ok=0
for i in $(seq 1 15); do
  if lsof -nP -iTCP:"$TCP_PORT" -sTCP:LISTEN >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ "$ok" -ne 1 ]; then
  tail -20 "$DEST/logs/bridge.log" "$DEST/logs/launchd.log" 2>/dev/null || true
  fail "service did not start - see logs above"
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '<host-ip>')"
say "Installed and running"
cat <<EOF

    Bridge version:  v$NEW_VER
    Savant profile:  wire to this host's IP ($IP), port $TCP_PORT
    Dashboard:       http://$IP:$HTTP_PORT/
    Config:          $DEST/config.json   (then: sudo openwx restart)
    Control:         openwx status | sudo openwx stop | start | restart | openwx logs
    Remove:          sudo $DEST/uninstall.sh

EOF
