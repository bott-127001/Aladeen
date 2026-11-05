# Fixture Specification: `tjl_11_unknown_availability_and_wick_precedence`

**Category**: synthetic_lifecycle_specification, source_settled  
**Scope**: Candle Interval Precedence & Non-Retroactivity  

## 1. Description & Strategy Context
Candle intervals are strictly half-open: `[open_time, close_time)`. A set created at Bar 7 close (`2026-10-02T00:00:00Z`) becomes available at that close.

## 2. Acceptance Assertions (OPEN-04)
- An intra-bar wick on that candle (e.g. at `2026-10-01T22:30:00Z`) **cannot be claimed as a retroactive tap**.
- `is_retroactive_wick_tap_allowed == False`.
- First eligible tap timestamp is on or after availability close (`2026-10-02T00:00:00Z`).
- If intra-bar sequence is unknown, status is `UNKNOWN_ORDER`.
