# Fixture Specification: `iss_04_wick_excursion_allowed`

**Category**: source_settled, end_to_end_msm_derived
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Candle wicks pierce beyond the frozen range boundaries (low 1.1350 < 1.1400 and high 1.2060 > 1.2000) while all marked body edges remain strictly inside. Confirms ISS per Section 5.

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
- **Lifecycle Status**: `CONFIRMED`
- **Confirmation Candle**: Bar #16 (None)
- **Completion Close Price**: `None` (Inside Boundary: `None`)
- **Structural Zones Formed**:
  - `RBS`: Bar #10 `[1.175, 1.206]` (is_line: `False`)
  - `BUYING_A_PLUS`: Bar #12 `[1.165, 1.168]` (is_line: `False`)

## 5. Candles Series Summary
Total candles: 17
Time span: 2026-10-01T00:00:00Z to 2026-10-01T16:00:00Z
