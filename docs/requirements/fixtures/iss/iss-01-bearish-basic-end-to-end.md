# Fixture Specification: `iss_01_bearish_basic_end_to_end`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Genuine end-to-end Bearish main structure. MSM execution confirms Main L2 (CH at Bar 4, price 1.2000) and identifies Main L3 (CL at Bar 7, price 1.1400) at Bar 9. Five internal upward points strictly inside boundary and completion close inside. Creates RBS zone on CH2 (Bar 14) and buying A+ zone on CL2 (Bar 16).

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
| 3 | `CH2` | #14 | 1.175 | Yes |
| 4 | `CL2` | #16 | 1.168 | Yes |
| 5 | `TENTATIVE_HIGH` | #18 | 1.192 | Yes |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `CONFIRMED`
- **Confirmation Candle**: Bar #20 (2026-10-01T21:00:00Z)
- **Completion Close Price**: `1.188` (Inside Boundary: `True`)
- **Structural Zones Formed**:
  - `RBS`: Bar #14 `[1.175, 1.178]` (is_line: `False`)
  - `BUYING_A_PLUS`: Bar #16 `[1.165, 1.168]` (is_line: `False`)

## 5. Candles Series Summary
Total candles: 21
Time span: 2026-10-01T00:00:00Z to 2026-10-01T20:00:00Z
