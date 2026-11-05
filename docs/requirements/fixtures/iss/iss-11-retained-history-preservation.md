# Fixture Specification: `iss_11_retained_history_preservation`

**Category**: synthetic_lifecycle_specification, source_settled
**Main Direction**: `BEARISH`

## 1. Description & Strategy Context
Lifecycle specification: Confirmed ISS zones and labels remain in history after later main continuation break.

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
- **Lifecycle Status**: `CONFIRMED_HISTORY_RETAINED`

## 5. Candles Series Summary
Total candles: 23
Time span: 2026-10-01T00:00:00Z to 2026-10-01T22:00:00Z
