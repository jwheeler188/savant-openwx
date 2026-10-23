# Changelog

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
