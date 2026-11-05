# Fixture Specification: `iss_10_main_choch_cancellation`

**Category**: source_settled, end_to_end_msm_derived
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Main CHOCH confirms (two consecutive closes > 1.2000) while internal candidate is unfinished. Active ISS candidate cancelled; confirmed history retained.

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
- **Lifecycle Status**: `MAIN_CHOCH_CANCELLED`

## 5. Candles Series Summary
Total candles: 12
Time span: 2026-10-01T00:00:00Z to 2026-10-01T11:00:00Z
