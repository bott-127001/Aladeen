# Fixture Specification: `iss_06_outside_range_completion_tracking_only`

**Category**: source_settled, end_to_end_msm_derived
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
All 5 marked points valid inside [1.1400, 1.2000], but completion candle closes at 1.1350 outside boundary. ISS not confirmed, no zones created, internal markings retained only for tracking.

## 2. Main Prerequisites & Captured Boundary
- **Main Level 2**: `CH` at Bar #0 (Price: `1.2`)
- **Main Level 3**: `tentative_low` at Bar #3 (Price: `1.14`)
- **Captured Boundary**: `[1.14, 1.2]` frozen at Bar #5
- **Internal Search Reference**: Bar #3
- **First Eligible Internal Pullback**: > Bar #5

## 3. Expected Internal Points
| Point # | Role | Bar Index | Body Edge Price | Inside Boundary |
|:---:|:---:|:---:|:---:|:---:|
| — | — | — | — | — |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY`

## 5. Candles Series Summary
Total candles: 17
Time span: 2026-10-01T00:00:00Z to 2026-10-01T16:00:00Z
