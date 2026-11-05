# Fixture Specification: `iss_01_bearish_basic_end_to_end`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Standard Bearish main structure with 5 internal upward points strictly inside boundary and completion close inside. Creates RBS zone on CH2 (Bar 10) and buying A+ zone on CL2 (Bar 12).

## 2. Main Prerequisites & Captured Boundary
- **Main Level 2**: `CH` at Bar #0 (Price: `1.2`)
- **Main Level 3**: `tentative_low` at Bar #3 (Price: `1.14`)
- **Captured Boundary**: `[1.14, 1.2]` frozen at Bar #5
- **Internal Search Reference**: Bar #3
- **First Eligible Internal Pullback**: > Bar #5

## 3. Expected Internal Points
| Point # | Role | Bar Index | Body Edge Price | Inside Boundary |
|:---:|:---:|:---:|:---:|:---:|
| 1 | `CH1` | #6 | 1.16 | Yes |
| 2 | `CL1` | #8 | 1.148 | Yes |
| 3 | `CH2` | #10 | 1.175 | Yes |
| 4 | `CL2` | #12 | 1.168 | Yes |
| 5 | `TENTATIVE_HIGH` | #14 | 1.192 | Yes |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `CONFIRMED`
- **Confirmation Candle**: Bar #16 (2026-10-01T17:00:00Z)
- **Completion Close Price**: `1.188` (Inside Boundary: `True`)
- **Structural Zones Formed**:
  - `RBS`: Bar #10 `[1.175, 1.178]` (is_line: `False`)
  - `BUYING_A_PLUS`: Bar #12 `[1.165, 1.168]` (is_line: `False`)

## 5. Candles Series Summary
Total candles: 17
Time span: 2026-10-01T00:00:00Z to 2026-10-01T16:00:00Z
