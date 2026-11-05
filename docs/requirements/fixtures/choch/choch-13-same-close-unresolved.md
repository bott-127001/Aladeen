# Fixture CHOCH-13: Same-Close Point 3 Identification & First CHOCH Close (Unresolved Boundary)

- **Source Authority**: `docs/strategy/Choch.pdf` Section 2 ("Point 3 must already be identified when the first qualifying CHOCH candle closes"), with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-08).
- **Fixture Category**: `unresolved_boundary`
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_same_close_point_3_identification_unresolved`)

## Description & Boundary Isolation
This fixture specifies the narrowly scoped edge case where the exact candle that identifies Point 3 upon completion (pullback candle `p2` at index 7) simultaneously closes strictly beyond the broken structural level (`close < last_support`).

- **Authoritative Text**:
  > *"Point 3 must already be identified when the first qualifying CHOCH candle closes."*
- **The Interpretation Question**:
  When pullback candle `p2` completes, Point 3 becomes established at that close. Does the completed close of `p2` itself count as the first qualifying CHOCH close ($c_1$), or must $c_1$ occur on a strictly later candle ($c_1 \ge p_2 + 1$)?
- **Current Status**:
  **`UNRESOLVED_PENDING_RECONCILIATION`**.
  In accordance with strict non-invention, neither "eligible" nor "ineligible" is assumed. This fixture asserts **NO forced boolean outcome** (`expected_confirmed: null`). Engines must not silently default to either behavior.

## Dataset & Static Geometry

| Chronological Index | Timestamp (UTC) | Open | High | Low | Close | Role / Behavior |
|---|---|---|---|---|---|---|
| 5 | 2026-10-01 20:00 | 1.145 | 1.160 | 1.142 | 1.155 | Point 3 peak (UB = 1.155, High = 1.160) |
| 6 | 2026-10-02 00:00 | 1.155 | 1.156 | 1.135 | 1.140 | Pullback candle 1 (Low = 1.135) |
| 7 | 2026-10-02 04:00 | 1.095 | 1.100 | 1.085 | 1.090 | Pullback candle 2 (`close < low[6]`) -> Point 3 identified. Also: `close = 1.090 < 1.105` (Last Support) |
| 8 | 2026-10-02 08:00 | 1.090 | 1.098 | 1.088 | 1.092 | Immediate next chronological candle. `close = 1.092 < 1.105` |

## Verified Static Geometry Checks
- `p2` (index 7) forms a valid 2-candle pullback: `close[7] < low[6]`.
- `p2` close is strictly below Last Support: `close[7] = 1.090 < 1.105`.
- Subsequent candle (index 8) close is strictly below Last Support: `close[8] = 1.092 < 1.105`.

## The Two Potential Interpretations
1. **Option A (Simultaneous Close Eligible)**:
   - $c_1 = \text{index } 7$ (`p2`), $c_2 = \text{index } 8$.
   - CHOCH would confirm at index 8 (`2026-10-02 12:00 UTC`).
2. **Option B (Strictly Later Candle Required)**:
   - $c_1 = \text{index } 8$, index 8 does not confirm; CHOCH requires a subsequent qualifying close at index 9 for $c_2$.

## Verification Contract
- `eligibility_status`: `"UNRESOLVED_PENDING_RECONCILIATION"`
- `expected_confirmed`: `null` (neither True nor False).
