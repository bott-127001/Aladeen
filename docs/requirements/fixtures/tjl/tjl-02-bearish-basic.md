# Fixture Specification: `tjl_02_bearish_basic_end_to_end`

**Category**: end_to_end_msm_derived, source_settled  
**Structure Direction**: `BEARISH` (`DOWNWARD`)  
**Timeframe**: `H1`  
**Feed ID**: `FEED_GBPUSD_H1`  

## 1. Description & Strategy Context
End-to-end Bearish market structure derived from actual MSM execution. At Bar 5, MSM confirms CH (Bar 4, price 1.2000) and CL (Bar 2, price 1.1850). At Bar 9, a 2-candle pullback completes, identifying active Tentative Low P3 (Bar 7, price 1.1400). At Bar 9 close, the first eligible current TJL set is created.

## 2. Directional Point-to-Label Mapping
- **TJL1**: Confirmed Low (`CL`) at Bar 2 (price 1.1850)
  - Zone: Low-Side `[1.1800, 1.1850]` (Bottom wick to lower body)
  - Level ID: `("FEED_GBPUSD_H1", "H1", "2026-10-01T02:00:00Z", "LOW")`
- **TJL2 / A+**: Latest Confirmed High (`CH` / LRM) at Bar 4 (price 1.2000)
  - Zone: High-Side `[1.2000, 1.2050]` (Upper body to top wick)
  - Level ID: `("FEED_GBPUSD_H1", "H1", "2026-10-01T04:00:00Z", "HIGH")`
- **Point 3 (P3)**: Active Tentative Low at Bar 7 (price 1.1400)
  - Tentative points never supply a TJL zone.

## 3. Set Lifecycle & Timing (OPEN-02)
- **Bar 5 (Labels Only)**: Points receive TJL1 and TJL2 labels, but current set is `None` (P3 is None).
- **Bar 9 (First Set Creation)**: Pullback completes at Bar 9. Current set forms with fingerprint `("FEED_GBPUSD_H1", "DOWNWARD", 4, 2, 7)`.
- **Member Eligibility Availability**: Bar 9 close time (`2026-10-01T10:00:00Z`).
- **Non-Replacement**: First set creation emits `outgoing_cancellation_intent = false`.
