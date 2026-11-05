# Fixture Specification: `tjl_01_bullish_basic_end_to_end`

**Category**: end_to_end_msm_derived, source_settled  
**Structure Direction**: `BULLISH` (`UPWARD`)  
**Timeframe**: `H1`  
**Feed ID**: `FEED_EURUSD_H1`  

## 1. Description & Strategy Context
End-to-end Bullish market structure derived from actual MSM execution. At Bar 4, MSM confirms CH (Bar 1, price 1.1350) and CL (Bar 4, price 1.1050). At Bar 7, a 2-candle pullback completes, identifying active Tentative High P3 (Bar 5, price 1.1550). At Bar 7 close, the first eligible current TJL set is created.

## 2. Directional Point-to-Label Mapping
- **TJL1**: Confirmed High (`CH`) at Bar 1 (price 1.1350)
  - Zone: High-Side `[1.1350, 1.1400]` (Upper body to top wick)
  - Level ID: `("FEED_EURUSD_H1", "H1", "2026-10-01T04:00:00+00:00", "HIGH")`
- **TJL2 / A+**: Latest Confirmed Low (`CL` / LSM) at Bar 4 (price 1.1050)
  - Zone: Low-Side `[1.1040, 1.1050]` (Bottom wick to lower body)
  - Level ID: `("FEED_EURUSD_H1", "H1", "2026-10-01T16:00:00+00:00", "LOW")`
- **Point 3 (P3)**: Active Tentative High at Bar 5 (price 1.1550)
  - Tentative points never supply a TJL zone.

## 3. Set Lifecycle & Timing (OPEN-02)
- **Bar 4 (Labels Only)**: Confirmed points receive TJL1 and TJL2 labels, but current set is `None` because active P3 is not yet identified.
- **Bar 7 (First Set Creation)**: Pullback completes at Bar 7. Current set forms with fingerprint `("FEED_EURUSD_H1", "UPWARD", 1, 4, 5)`.
- **Member Eligibility Availability**: Bar 7 close time (`2026-10-02T00:00:00Z`).
- **Non-Replacement**: First set creation emits `outgoing_cancellation_intent = false`.
