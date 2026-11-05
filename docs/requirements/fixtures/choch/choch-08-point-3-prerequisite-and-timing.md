# Fixture CHOCH-08: Point 3 Prerequisite and Timing

- **Source Authority**: `docs/strategy/Choch.pdf` Section 2, with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-08, OPEN-09).
- **Fixture Category**: `synthetic_prerequisite_unit`, `source_settled`
- **Machine-Readable Targets**:
  - `tests/fixtures/choch_acceptance.json` (`choch_rejected_when_no_active_point_3`)
  - `tests/fixtures/choch_acceptance.json` (`choch_closes_strictly_before_point_3_identification_rejected`)
  - `tests/fixtures/choch_acceptance.json` (`choch_settled_later_candle_choch_confirmed`)
  - `tests/fixtures/choch_acceptance.json` (`choch_active_point_3_not_replaced_by_later_raw_extreme`)

## Description
A valid Change of Character requires an active Tentative Point 3 established by the underlying MSM pullback rules:
1. **Absence of Point 3**: If no valid 2-candle pullback has completed in the current cycle, Point 3 does not exist and CHOCH evaluation fails closed.
2. **Closes Strictly Before Identification Ineligible**: Any candle completing strictly *before* Point 3 identification ($< p_2$, such as pullback candle 1 at index 6) cannot count toward CHOCH confirmation.
3. **Source-Settled Later-Candle Path**: When the first qualifying close occurs on a candle strictly after Point 3 identification ($c_1 \ge p_2 + 1$), eligibility is established and fully settled.
4. **Extreme Invariance**: Once active, Point 3 is fixed at the identified swing extreme candle (Index 5). A subsequent candle with a higher raw wick or body that does not form a new cycle does not alter Point 3 or the Double Top zone reference.

*(Note: The specific edge case where the identification candle itself closes beyond support, $c_1 == p_2$, is isolated separately in Fixture CHOCH-13 as an unresolved boundary case pending source reconciliation).*

## Scenario A: Missing Active Point 3
- Upward cycle with Last Support at `1.105`.
- Price falls directly below Last Support without completing a pullback from a new high.
- Result: `confirmed = false`, `reason = "ACTIVE_POINT_3_ABSENT"`.

## Scenario B: Closes Strictly Before Point 3 Identification
- Upward cycle with Last Support at `1.105`.
- Pullback candle 1 (index 6, completing strictly before Point 3 identification at index 7) closes at `1.095 < 1.105`.
- Evaluation: At index 6, Point 3 is not yet identified. This close cannot count toward CHOCH confirmation.
- Result: `confirmed = false`, `reason = "CANDLE_COMPLETED_STRICTLY_BEFORE_POINT_3_IDENTIFICATION"`.

## Scenario C: Settled Later-Candle Confirmation
- Point 3 identified upon completion of pullback candle 2 at index 7.
- Candle 8 (first candle strictly after identification) closes at `1.095 < 1.105` ($c_1$).
- Candle 9 (immediate next chronological candle) closes at `1.085 < 1.105` ($c_2$).
- Result: `confirmed = true`, `type = "BEARISH_CHOCH"`, `c1_idx = 8`, `c2_idx = 9`.

## Scenario D: Unconfirmed Raw Extreme
- Active Point 3 identified at candle 5 (`UB = 1.155, High = 1.160`).
- Candle 6 wicks up to `1.165` but does not initiate a new cycle.
- CHOCH completes at candle 9.
- Double Top zone must be anchored to candle 5 (`[1.155, 1.160]`), NOT candle 6.
- Result: `confirmed = true`, `double_top_source_candle_idx = 5`.
