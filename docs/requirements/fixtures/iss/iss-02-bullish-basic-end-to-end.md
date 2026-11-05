# Fixture Specification: `iss_02_bullish_basic_end_to_end`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BULLISH`

## 1. Description & Strategy Context
Standard Bullish main structure with 5 internal downward points strictly inside boundary and completion close inside. Creates SBR zone on CL2 (Bar 10) and selling A+ zone on CH2 (Bar 12).

## 2. Main Prerequisites & Captured Boundary
- **Main Level 2**: `CL` at Bar #0 (Price: `1.1`)
- **Main Level 3**: `tentative_high` at Bar #3 (Price: `1.16`)
- **Captured Boundary**: `[1.1, 1.16]` frozen at Bar #5
- **Internal Search Reference**: Bar #3
- **First Eligible Internal Pullback**: > Bar #5

## 3. Expected Internal Points
| Point # | Role | Bar Index | Body Edge Price | Inside Boundary |
|:---:|:---:|:---:|:---:|:---:|
| 1 | `CL1` | #6 | 1.14 | Yes |
| 2 | `CH1` | #8 | 1.152 | Yes |
| 3 | `CL2` | #10 | 1.125 | Yes |
| 4 | `CH2` | #12 | 1.132 | Yes |
| 5 | `TENTATIVE_LOW` | #14 | 1.108 | Yes |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `CONFIRMED`
- **Confirmation Candle**: Bar #16 (2026-10-01T17:00:00Z)
- **Completion Close Price**: `1.112` (Inside Boundary: `True`)
- **Structural Zones Formed**:
  - `SBR`: Bar #10 `[1.122, 1.125]` (is_line: `False`)
  - `SELLING_A_PLUS`: Bar #12 `[1.132, 1.135]` (is_line: `False`)

## 5. Candles Series Summary
Total candles: 17
Time span: 2026-10-01T00:00:00Z to 2026-10-01T16:00:00Z
