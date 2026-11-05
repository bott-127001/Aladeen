# Fixture Specification: `iss_07_no_revival_under_same_main_level_3`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Subsequent internal price action following an outside-range completion attempt cannot revive ISS eligibility under the same main level 3.

## 2. Main Prerequisites & Captured Boundary
- **Main Level 2**: `CH` at Bar #4 (Price: `1.2`)
- **Main Level 3**: `tentative_low` at Bar #7 (Price: `1.14`)
- **Captured Boundary**: `[1.14, 1.2]` frozen at Bar #9
- **Internal Search Reference**: Bar #7
- **First Eligible Internal Pullback**: > Bar #9

## 3. Expected Internal Points
| Point # | Role | Bar Index | Body Edge Price | Inside Boundary |
|:---:|:---:|:---:|:---:|:---:|
| — | — | — | — | — |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `PERMANENTLY_INELIGIBLE_FOR_CURRENT_MAIN_L3`

## 5. Candles Series Summary
Total candles: 24
Time span: 2026-10-01T00:00:00Z to 2026-10-01T23:00:00Z
