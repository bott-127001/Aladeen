# Fixture CHOCH-08: Point 3 Prerequisite and Eligibility Timing

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 2 & `docs/requirements/approved-clarifications.md` (OPEN-01, OPEN-08, OPEN-09)
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_rejected_when_no_active_point_3`, `choch_closes_before_point_3_identification_rejected`, `choch_active_point_3_not_replaced_by_later_raw_extreme`)

## Description
A valid Change of Character requires an active Tentative Point 3. 
1. If no pullback has formed in the current cycle, Point 3 does not exist and CHOCH evaluation must fail closed.
2. Closes that occur before or during the 2-candle pullback that identifies Point 3 cannot count toward CHOCH confirmation. The first qualifying close ($c_1$) must occur strictly after Point 3 identification ($c_1 > p_2$).
3. Once active, Point 3 is fixed at the identified swing extreme candle. A subsequent candle with a higher raw wick or body that does not form a new cycle does NOT update Point 3 or the Double Top zone reference.

## Scenario A: Missing Active Point 3
- Upward cycle with Last Support at `1.105`.
- Price falls directly below Last Support without completing a pullback from a new high.
- Result: `confirmed = false`, `reason = "ACTIVE_POINT_3_ABSENT"`.

## Scenario B: Closes Prior to Point 3 Identification
- Last Support at `1.105`.
- Pullback starts at candle 6, completed at candle 7.
- Candle 6 closes at `1.095 < 1.105`, Candle 7 closes at `1.090 < 1.105`.
- Evaluation: At candle 6, Point 3 is not yet active. At candle 7, Point 3 becomes active upon completion, so candle 7's close cannot count retrospectively.
- First eligible candle for $c_1$ is candle 8.
- Result: `confirmed_at_idx_7 = false`, `reason = "CANNOT_COUNT_CLOSES_PRIOR_TO_POINT_3_IDENTIFICATION"`.

## Scenario C: Unconfirmed Raw Extreme
- Active Point 3 identified at candle 5 (`UB = 1.155, High = 1.160`).
- Candle 6 wicks up to `1.165` but does not initiate a new cycle.
- CHOCH completes at candle 9.
- Double Top zone must be anchored to candle 5 (`[1.155, 1.160]`), NOT candle 6.
- Result: `confirmed = true`, `double_top_source_candle_idx = 5`.
