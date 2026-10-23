# Savant OpenWx — state reference (v2.0.0)

All 248 states exist in the Blueprint profile under the same names, on the component's logical component **Weather**.
Drag them from Blueprint's State browser (Component tab) into labels, triggers and workflows.

- `H3_` / `H12_` / `H24_` states are forecasts for the next 3/12/24 hours, starting at the current hour.
- Temperatures in °F and speeds in mph (or °C and km/h when the bridge's `units` is `metric`).
- An empty state shows as `--` in a Savant label.
- Integer states can be compared directly in triggers.

## Display text (for labels)

| State | Type | Meaning |
|---|---|---|
| `ALERTS_LIST` | string | Every active alert with its end time, most severe first, e.g. Wind Advisory until Fri 6:00 PM · Air Quality Alert until Fri 9:30 PM; or No active alerts |
| `CUR_TEMP_TEXT` | string | Now: temperature as text, e.g. 67° |
| `CUR_FEELS_TEXT` | string | Now: e.g. Feels like 70° |
| `CUR_WIND_TEXT` | string | Now: e.g. 12 mph SSE, gusts 19 (Calm when still) |
| `CUR_LINE` | string | Now: one line, e.g. 67° Pleasant & Partly Cloudy |
| `H3_HILO_TEXT` | string | H3: e.g. 84° / 68° |
| `H3_LINE` | string | Next 3h: one line matching D*_LINE, e.g. Next 3h 67° / 56° Clear |
| `H12_HILO_TEXT` | string | H12: e.g. 84° / 68° |
| `H12_LINE` | string | Next 12h: one line matching D*_LINE, e.g. Next 12h 67° / 56° Clear |
| `H24_HILO_TEXT` | string | H24: e.g. 84° / 68° |
| `H24_LINE` | string | Next 24h: one line matching D*_LINE, e.g. Next 24h 67° / 56° Clear |
| `HR1_TEMP_TEXT` | string | Hourly slot 1: e.g. 67° |
| `HR2_TEMP_TEXT` | string | Hourly slot 2: e.g. 67° |
| `HR3_TEMP_TEXT` | string | Hourly slot 3: e.g. 67° |
| `HR4_TEMP_TEXT` | string | Hourly slot 4: e.g. 67° |
| `HR5_TEMP_TEXT` | string | Hourly slot 5: e.g. 67° |
| `HR6_TEMP_TEXT` | string | Hourly slot 6: e.g. 67° |
| `HR7_TEMP_TEXT` | string | Hourly slot 7: e.g. 67° |
| `HR8_TEMP_TEXT` | string | Hourly slot 8: e.g. 67° |
| `D0_HILO_TEXT` | string | Day 0: e.g. 84° / 68° |
| `D0_LINE` | string | Day 0: one line, e.g. Thu 84° / 68° Stormy 70% |
| `D1_HILO_TEXT` | string | Day 1: e.g. 84° / 68° |
| `D1_LINE` | string | Day 1: one line, e.g. Thu 84° / 68° Stormy 70% |
| `D2_HILO_TEXT` | string | Day 2: e.g. 84° / 68° |
| `D2_LINE` | string | Day 2: one line, e.g. Thu 84° / 68° Stormy 70% |
| `D3_HILO_TEXT` | string | Day 3: e.g. 84° / 68° |
| `D3_LINE` | string | Day 3: one line, e.g. Thu 84° / 68° Stormy 70% |
| `D4_HILO_TEXT` | string | Day 4: e.g. 84° / 68° |
| `D4_LINE` | string | Day 4: one line, e.g. Thu 84° / 68° Stormy 70% |
| `ALERT_TEXT` | string | e.g. ALERT: Wind Advisory until Wed 9:00 PM, or No active alerts |

## System and data sources

| State | Type | Meaning |
|---|---|---|
| `SYS_ONLINE` | integer | 1 = bridge has fresh data, 0 = stale/failed |
| `SYS_LAST_UPDATE` | string | Time of last successful update (e.g. 10:35 PM) |
| `SYS_LAST_UPDATE_EPOCH` | integer | Unix time of last successful update |
| `SYS_LOCATION_NAME` | string | Resolved location name |
| `SYS_LOCATION_SOURCE` | string | override / site / default |
| `SYS_LAT` | string | Latitude in use |
| `SYS_LON` | string | Longitude in use |
| `SYS_UNITS` | string | imperial / metric |
| `SYS_ERROR` | string | Last error message, blank when healthy |
| `SYS_CURRENT_SOURCE` | string | Where current conditions came from: Station KDWH / Forecast hour (station report too old) / Open-Meteo model |
| `SYS_STATION_ID` | string | NWS observation station used for current conditions, e.g. KDWH |
| `SYS_STATION_NAME` | string | Station name, e.g. Houston, David Wayne Hooks Memorial Airport |
| `SYS_STATION_DISTANCE` | string | Distance and direction from the site to the station, e.g. 11 mi NW |
| `SYS_STATION_OBS_TIME` | string | Time of the station report in use, e.g. 6:15 PM |
| `SYS_CONTACT_SET` | integer | 1 = a real contact email is set (Blueprint Contact Email or config.json); 0 = still a placeholder |
| `SYS_FORECAST_SOURCE` | string | Where the forecast came from: NWS (free) / Open-Meteo (API key) / Open-Meteo free (private...) / NWS (Open-Meteo unavailable) |
| `SYS_MEMORY_MB` | integer | Bridge process memory (MB); it restarts itself above max_memory_mb |
| `SYS_SUN_SOURCE` | string | Sunrise/sunset source: US Naval Observatory, or Calculated if USNO is unreachable |
| `SYS_UV_SOURCE` | string | UV source: EPA (today) + MET Norway clear-sky (later days) / Open-Meteo / blank if none |

## Current conditions

| State | Type | Meaning |
|---|---|---|
| `CUR_TEMP` | integer | Now: Temperature |
| `CUR_FEELS` | integer | Now: Feels-like temperature |
| `CUR_HUMIDITY` | integer | Now: Relative humidity % |
| `CUR_DEWPOINT` | integer | Now: Dew point |
| `CUR_WIND` | integer | Now: Wind speed |
| `CUR_GUST` | integer | Now: Wind gust |
| `CUR_WIND_DIR` | string | Now: Wind direction (N, NE, ...) |
| `CUR_WIND_DEG` | integer | Now: Wind direction degrees |
| `CUR_UV` | integer | Now: UV index |
| `CUR_UV_LEVEL` | string | Now: Low / Moderate / High / Very High / Extreme |
| `CUR_CLOUD` | integer | Now: Cloud cover % |
| `CUR_PRECIP` | string | Now: Precipitation this hour |
| `CUR_PRESSURE` | integer | Now: Sea-level pressure (hPa) |
| `CUR_IS_DAY` | integer | Now: 1 = daytime |
| `CUR_SKY` | string | Now: Sunny / Clear / Mostly Sunny / Partly Cloudy / Mostly Cloudy / Overcast |
| `CUR_WEATHER` | string | Now: Sunny / Clear / Partly Cloudy / Cloudy / Rainy / Stormy / Snowy / Icy / Foggy |
| `CUR_COMFORT` | string | Now: Hot / Warm / Pleasant / Cool / Cold / Freezing |
| `CUR_SUMMARY` | string | Now: e.g. Warm & Sunny |
| `CUR_ICON` | string | Now: Icon key: clear-day, clear-night, partly-day, partly-night, cloudy, fog, drizzle, rain, thunder, snow, sleet, wind |

## Next 3 hours

| State | Type | Meaning |
|---|---|---|
| `H3_TEMP_HIGH` | integer | Next 3h: High temperature |
| `H3_TEMP_LOW` | integer | Next 3h: Low temperature |
| `H3_FEELS_HIGH` | integer | Next 3h: Highest feels-like |
| `H3_FEELS_LOW` | integer | Next 3h: Lowest feels-like |
| `H3_RAIN_CHANCE` | integer | Next 3h: Max precipitation chance % |
| `H3_RAIN_TOTAL` | string | Next 3h: Total expected precipitation |
| `H3_WIND_MAX` | integer | Next 3h: Max sustained wind |
| `H3_GUST_MAX` | integer | Next 3h: Max wind gust |
| `H3_GUST_MAX_TIME` | string | Next 3h: Hour of max gust |
| `H3_UV_MAX` | integer | Next 3h: Max UV index |
| `H3_SKY` | string | Next 3h: Most common sky condition |
| `H3_WEATHER` | string | Next 3h: Most significant weather |
| `H3_COMFORT` | string | Next 3h: Comfort |
| `H3_SUMMARY` | string | Next 3h: Plain-language summary |
| `H3_ICON` | string | Next 3h: Icon key |
| `H3_RAIN_EXPECTED` | integer | Next 3h: 1 = rain chance at/above threshold |
| `H3_FREEZE_EXPECTED` | integer | Next 3h: 1 = temp at/below freezing |

## Next 12 hours

| State | Type | Meaning |
|---|---|---|
| `H12_TEMP_HIGH` | integer | Next 12h: High temperature |
| `H12_TEMP_LOW` | integer | Next 12h: Low temperature |
| `H12_FEELS_HIGH` | integer | Next 12h: Highest feels-like |
| `H12_FEELS_LOW` | integer | Next 12h: Lowest feels-like |
| `H12_RAIN_CHANCE` | integer | Next 12h: Max precipitation chance % |
| `H12_RAIN_TOTAL` | string | Next 12h: Total expected precipitation |
| `H12_WIND_MAX` | integer | Next 12h: Max sustained wind |
| `H12_GUST_MAX` | integer | Next 12h: Max wind gust |
| `H12_GUST_MAX_TIME` | string | Next 12h: Hour of max gust |
| `H12_UV_MAX` | integer | Next 12h: Max UV index |
| `H12_SKY` | string | Next 12h: Most common sky condition |
| `H12_WEATHER` | string | Next 12h: Most significant weather |
| `H12_COMFORT` | string | Next 12h: Comfort |
| `H12_SUMMARY` | string | Next 12h: Plain-language summary |
| `H12_ICON` | string | Next 12h: Icon key |
| `H12_RAIN_EXPECTED` | integer | Next 12h: 1 = rain chance at/above threshold |
| `H12_FREEZE_EXPECTED` | integer | Next 12h: 1 = temp at/below freezing |

## Next 24 hours

| State | Type | Meaning |
|---|---|---|
| `H24_TEMP_HIGH` | integer | Next 24h: High temperature |
| `H24_TEMP_LOW` | integer | Next 24h: Low temperature |
| `H24_FEELS_HIGH` | integer | Next 24h: Highest feels-like |
| `H24_FEELS_LOW` | integer | Next 24h: Lowest feels-like |
| `H24_RAIN_CHANCE` | integer | Next 24h: Max precipitation chance % |
| `H24_RAIN_TOTAL` | string | Next 24h: Total expected precipitation |
| `H24_WIND_MAX` | integer | Next 24h: Max sustained wind |
| `H24_GUST_MAX` | integer | Next 24h: Max wind gust |
| `H24_GUST_MAX_TIME` | string | Next 24h: Hour of max gust |
| `H24_UV_MAX` | integer | Next 24h: Max UV index |
| `H24_SKY` | string | Next 24h: Most common sky condition |
| `H24_WEATHER` | string | Next 24h: Most significant weather |
| `H24_COMFORT` | string | Next 24h: Comfort |
| `H24_SUMMARY` | string | Next 24h: Plain-language summary |
| `H24_ICON` | string | Next 24h: Icon key |
| `H24_RAIN_EXPECTED` | integer | Next 24h: 1 = rain chance at/above threshold |
| `H24_FREEZE_EXPECTED` | integer | Next 24h: 1 = temp at/below freezing |

## Hourly strip (every 3 hours)

| State | Type | Meaning |
|---|---|---|
| `HR1_TIME` | string | Hourly slot 1 (+0h): Hour label |
| `HR1_TEMP` | integer | Hourly slot 1 (Now): current temperature |
| `HR1_RAIN` | integer | Hourly slot 1 (+0h): Rain chance % |
| `HR1_GUST` | integer | Hourly slot 1 (+0h): Gust |
| `HR1_ICON` | string | Hourly slot 1 (+0h): Icon key |
| `HR2_TIME` | string | Hourly slot 2 (+3h): Hour label |
| `HR2_TEMP` | integer | Hourly slot 2 (+3h): Temperature |
| `HR2_RAIN` | integer | Hourly slot 2 (+3h): Rain chance % |
| `HR2_GUST` | integer | Hourly slot 2 (+3h): Gust |
| `HR2_ICON` | string | Hourly slot 2 (+3h): Icon key |
| `HR3_TIME` | string | Hourly slot 3 (+6h): Hour label |
| `HR3_TEMP` | integer | Hourly slot 3 (+6h): Temperature |
| `HR3_RAIN` | integer | Hourly slot 3 (+6h): Rain chance % |
| `HR3_GUST` | integer | Hourly slot 3 (+6h): Gust |
| `HR3_ICON` | string | Hourly slot 3 (+6h): Icon key |
| `HR4_TIME` | string | Hourly slot 4 (+9h): Hour label |
| `HR4_TEMP` | integer | Hourly slot 4 (+9h): Temperature |
| `HR4_RAIN` | integer | Hourly slot 4 (+9h): Rain chance % |
| `HR4_GUST` | integer | Hourly slot 4 (+9h): Gust |
| `HR4_ICON` | string | Hourly slot 4 (+9h): Icon key |
| `HR5_TIME` | string | Hourly slot 5 (+12h): Hour label |
| `HR5_TEMP` | integer | Hourly slot 5 (+12h): Temperature |
| `HR5_RAIN` | integer | Hourly slot 5 (+12h): Rain chance % |
| `HR5_GUST` | integer | Hourly slot 5 (+12h): Gust |
| `HR5_ICON` | string | Hourly slot 5 (+12h): Icon key |
| `HR6_TIME` | string | Hourly slot 6 (+15h): Hour label |
| `HR6_TEMP` | integer | Hourly slot 6 (+15h): Temperature |
| `HR6_RAIN` | integer | Hourly slot 6 (+15h): Rain chance % |
| `HR6_GUST` | integer | Hourly slot 6 (+15h): Gust |
| `HR6_ICON` | string | Hourly slot 6 (+15h): Icon key |
| `HR7_TIME` | string | Hourly slot 7 (+18h): Hour label |
| `HR7_TEMP` | integer | Hourly slot 7 (+18h): Temperature |
| `HR7_RAIN` | integer | Hourly slot 7 (+18h): Rain chance % |
| `HR7_GUST` | integer | Hourly slot 7 (+18h): Gust |
| `HR7_ICON` | string | Hourly slot 7 (+18h): Icon key |
| `HR8_TIME` | string | Hourly slot 8 (+21h): Hour label |
| `HR8_TEMP` | integer | Hourly slot 8 (+21h): Temperature |
| `HR8_RAIN` | integer | Hourly slot 8 (+21h): Rain chance % |
| `HR8_GUST` | integer | Hourly slot 8 (+21h): Gust |
| `HR8_ICON` | string | Hourly slot 8 (+21h): Icon key |

## Daily forecast (D0 = today … D4)

| State | Type | Meaning |
|---|---|---|
| `D0_NAME` | string | Day 0: Day name (Today, Thu, ...) |
| `D0_HIGH` | integer | Day 0: High |
| `D0_LOW` | integer | Day 0: Low |
| `D0_RAIN_CHANCE` | integer | Day 0: Rain chance % |
| `D0_GUST_MAX` | integer | Day 0: Max gust |
| `D0_UV_MAX` | integer | Day 0: Max UV |
| `D0_WEATHER` | string | Day 0: Weather |
| `D0_SUMMARY` | string | Day 0: Summary |
| `D0_ICON` | string | Day 0: Icon key |
| `D1_NAME` | string | Day 1: Day name (Today, Thu, ...) |
| `D1_HIGH` | integer | Day 1: High |
| `D1_LOW` | integer | Day 1: Low |
| `D1_RAIN_CHANCE` | integer | Day 1: Rain chance % |
| `D1_GUST_MAX` | integer | Day 1: Max gust |
| `D1_UV_MAX` | integer | Day 1: Max UV |
| `D1_WEATHER` | string | Day 1: Weather |
| `D1_SUMMARY` | string | Day 1: Summary |
| `D1_ICON` | string | Day 1: Icon key |
| `D2_NAME` | string | Day 2: Day name (Today, Thu, ...) |
| `D2_HIGH` | integer | Day 2: High |
| `D2_LOW` | integer | Day 2: Low |
| `D2_RAIN_CHANCE` | integer | Day 2: Rain chance % |
| `D2_GUST_MAX` | integer | Day 2: Max gust |
| `D2_UV_MAX` | integer | Day 2: Max UV |
| `D2_WEATHER` | string | Day 2: Weather |
| `D2_SUMMARY` | string | Day 2: Summary |
| `D2_ICON` | string | Day 2: Icon key |
| `D3_NAME` | string | Day 3: Day name (Today, Thu, ...) |
| `D3_HIGH` | integer | Day 3: High |
| `D3_LOW` | integer | Day 3: Low |
| `D3_RAIN_CHANCE` | integer | Day 3: Rain chance % |
| `D3_GUST_MAX` | integer | Day 3: Max gust |
| `D3_UV_MAX` | integer | Day 3: Max UV |
| `D3_WEATHER` | string | Day 3: Weather |
| `D3_SUMMARY` | string | Day 3: Summary |
| `D3_ICON` | string | Day 3: Icon key |
| `D4_NAME` | string | Day 4: Day name (Today, Thu, ...) |
| `D4_HIGH` | integer | Day 4: High |
| `D4_LOW` | integer | Day 4: Low |
| `D4_RAIN_CHANCE` | integer | Day 4: Rain chance % |
| `D4_GUST_MAX` | integer | Day 4: Max gust |
| `D4_UV_MAX` | integer | Day 4: Max UV |
| `D4_WEATHER` | string | Day 4: Weather |
| `D4_SUMMARY` | string | Day 4: Summary |
| `D4_ICON` | string | Day 4: Icon key |

## Sun

| State | Type | Meaning |
|---|---|---|
| `SUN_RISE` | string | Sunrise today |
| `SUN_SET` | string | Sunset today |
| `SUN_DAWN` | string | Civil dawn today (sky getting light, about 25 min before sunrise) |
| `SUN_DUSK` | string | Civil dusk today (sky dark, about 25 min after sunset) |

## NWS alerts

| State | Type | Meaning |
|---|---|---|
| `ALERT_ACTIVE` | integer | 1 = any NWS watch/warning/advisory active |
| `ALERT_COUNT` | integer | Number of different active alerts (duplicates of the same alert counted once) |
| `ALERT_HIGHEST_SEVERITY` | string | Extreme / Severe / Moderate / Minor / None |
| `ALERT_HEADLINE` | string | Headline of most severe alert |
| `ALERT_EVENTS` | string | Comma-separated active event names |
| `ALERT_FREEZE` | integer | 1 = active freeze-related alert |
| `ALERT_WIND` | integer | 1 = active wind-related alert |
| `ALERT_TORNADO` | integer | 1 = active tornado-related alert |
| `ALERT_TSTORM` | integer | 1 = active tstorm-related alert |
| `ALERT_FLOOD` | integer | 1 = active flood-related alert |
| `ALERT_HEAT` | integer | 1 = active heat-related alert |
| `ALERT_WINTER` | integer | 1 = active winter-related alert |
| `ALERT_TROPICAL` | integer | 1 = active tropical-related alert |
| `ALERT_FIRE` | integer | 1 = active fire-related alert |
| `ALERT_FOG` | integer | 1 = active fog-related alert |
| `ALERT1_EVENT` | string | Alert 1: Event name |
| `ALERT1_SEVERITY` | string | Alert 1: Severity |
| `ALERT1_EXPIRES` | string | Alert 1: Ends/expires |
| `ALERT1_HEADLINE` | string | Alert 1: Headline |
| `ALERT2_EVENT` | string | Alert 2: Event name |
| `ALERT2_SEVERITY` | string | Alert 2: Severity |
| `ALERT2_EXPIRES` | string | Alert 2: Ends/expires |
| `ALERT2_HEADLINE` | string | Alert 2: Headline |
| `ALERT3_EVENT` | string | Alert 3: Event name |
| `ALERT3_SEVERITY` | string | Alert 3: Severity |
| `ALERT3_EXPIRES` | string | Alert 3: Ends/expires |
| `ALERT3_HEADLINE` | string | Alert 3: Headline |

## Automation flags

| State | Type | Meaning |
|---|---|---|
| `ACT_WIND_PROTECT` | integer | 1 = gust now or within next 3h >= wind_protect_gust |
| `ACT_RAIN_SOON` | integer | 1 = rain chance within next 3h >= rain_soon_chance |
| `ACT_FREEZE_TONIGHT` | integer | 1 = next 12h low <= freeze_temp or freeze alert active |
| `ACT_HIGH_UV` | integer | 1 = UV now >= high_uv |
| `ACT_HEAT` | integer | 1 = feels-like now >= heat_feels or heat alert active |

## Thresholds in use

| State | Type | Meaning |
|---|---|---|
| `TH_WIND_PROTECT_GUST` | integer | Threshold in use: wind_protect_gust |
| `TH_RAIN_SOON_CHANCE` | integer | Threshold in use: rain_soon_chance |
| `TH_RAIN_EXPECTED_CHANCE` | integer | Threshold in use: rain_expected_chance |
| `TH_FREEZE_TEMP` | integer | Threshold in use: freeze_temp |
| `TH_HIGH_UV` | integer | Threshold in use: high_uv |
| `TH_HEAT_FEELS` | integer | Threshold in use: heat_feels |
| `TH_WIND_ICON_GUST` | integer | Threshold in use: wind_icon_gust |
| `TH_SOURCE` | string | Which thresholds were set from Savant (blank = all from config.json) |
