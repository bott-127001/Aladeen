# Fixture Specification: `iss_05_out_of_bounds_marked_point_rejection`

**Category**: end_to_end_msm_derived, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Marked internal point 3 body edge (1.2020) breaches frozen upper boundary (1.2000). Candidate permanently rejected, internal markings removed, zero zones created.

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
- **Lifecycle Status**: `OUT_OF_BOUNDS_REJECTED`
- **Rejection Reason**: Marked level CH2 price 1.2020 exceeds upper boundary 1.2000

## 5. Candles Series Summary
Total candles: 21
Time span: 2026-10-01T00:00:00Z to 2026-10-01T20:00:00Z
