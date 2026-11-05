# Fixture Specification: `iss_03_boundary_equality`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Marked internal point 5 body-edge price exactly equals captured boundary price (1.2000). Verified that boundary equality satisfies the inclusive range condition.

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
| 5 | `TENTATIVE_HIGH` | #18 | 1.2 | Yes |

## 4. Expected Outcome & Lifecycle Status
- **Lifecycle Status**: `CONFIRMED`
- **Confirmation Candle**: Bar #20 (None)
- **Completion Close Price**: `1.188` (Inside Boundary: `True`)

## 5. Candles Series Summary
Total candles: 21
Time span: 2026-10-01T00:00:00Z to 2026-10-01T20:00:00Z
