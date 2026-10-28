# Changelog

## 2.0.2

2.0.1 was not released; its changes are included here.

- The Blueprint profile now ships as an import package, `profile/blueprint-import/`: `openwx_weatherbridge.xml` (the profile), `.htm` (the full user manual, shown on the component's **Documentation** tab) and `.icns` (the component icon), side by side. Blueprint only picks up the page and icon from beside the profile, so keep the three files together. The profile is no longer in `profile/` itself: delete the 2.0.0 entry from Blueprint's library, then import from `blueprint-import`.
- `generate_profile.py` builds the Documentation tab page from `MANUAL.md` and `STATES.md`, screenshots included, so the two never drift apart. `make_icon.sh` builds the icon from `icon.svg`.
- No bridge or state changes. Re-import the profile; reinstalling the bridge is optional (only its version number changed).

## 2.0.0 — first public release

Savant OpenWx: weather, forecast and NWS alerts for Savant as plain states, via a small bridge service on the Savant host.

- 248 Savant states: current conditions, next 3/12/24 hours, hourly strip, 5-day forecast, sun times, NWS alerts, ready-to-display text, automation flags.
- Free data by default (US): National Weather Service forecast, observations and alerts; EPA UV (today); MET Norway clear-sky UV (later days); US Naval Observatory sun times.
- Optional Open-Meteo API key for a commercial worldwide forecast; `private` uses Open-Meteo's free tier for personal testing only.
- Everything set from Blueprint: location (site coordinates or override), contact email, API key, six automation thresholds.
- Current conditions from the nearest NWS station with a fresh report (3 nearest tried); values the API leaves empty are read from the station's raw report.
- Resilient: bad location falls back, bad key falls back to NWS, USNO/MET outages fall back, alerts de-duplicated.
- macOS installer/uninstaller for the Savant Mac mini Pro host (launchd service, memory watchdog, clean shutdown), `openwx` control command, Linux systemd unit.
- Web dashboard on port 8642.

Pre-release builds (1.x) were tested privately under a different name.
