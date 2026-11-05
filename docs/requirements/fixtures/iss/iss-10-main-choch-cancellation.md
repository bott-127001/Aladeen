# Fixture Specification: `iss_10_main_choch_cancellation`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Main CHOCH confirms (two consecutive closes > 1.2000 at Bar 15) while internal candidate is unfinished. Active ISS candidate cancelled; confirmed history retained.

## 2. Main Prerequisites & Captured Boundary
- **Main Level 2**: `CH` at Bar #4 (Price: `1.2`)
- **Main Level 3**: `tentative_low` at Bar #7 (Price: `1.14`)
- **Captured Boundary**: `[1.14, 1.2]` frozen at Bar #9
- **Internal Search Reference**: Bar #7
- **First Eligible Internal Pullback**: > Bar #9

## 3. Expected Internal Points
| Point # | Role | Bar Index | Body Edge Price | Inside Boundary |
|:---:|:---:|:---:|:---:|:---:|
| 1 | `CH1` | #10 | 1.16 | Yes |
| 2 | `CL1` | #12 | 1.148 | Yes |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `MAIN_CHOCH_CANCELLED`
- **Cancellation Candle**: Bar #15

## 5. Candles Series Summary
Total candles: 16
Time span: 2026-10-01T00:00:00Z to 2026-10-01T15:00:00Z
