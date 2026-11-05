# Fixture CHOCH-11: Cycle Restart Reference and Post-Confirmation Pullback Restriction

- **Source Authority**: `docs/strategy/Choch.pdf` Section 3.3, with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-08).
- **Fixture Category**: `synthetic_prerequisite_unit`, `source_settled`
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_restart_reference_and_post_confirmation_pullback_restriction`)

## Description
Upon confirmation of a Change of Character:
1. **Cycle Termination**: The prior MSM cycle terminates immediately.
2. **Direction Inversion**: The market structure direction reverses (e.g., `UPWARD` becomes `DOWNWARD`).
3. **Cycle History Preservation**: All historical confirmed swing points, break levels, and confirmation timestamps are preserved intact for charting and audit.
4. **New Cycle Search Reference**: The search reference candle for the new direction is set to the original candle of the active Point 3 that initiated the CHOCH cycle (e.g., Index 5).
5. **Post-Confirmation Pullback Restriction**: The first pullback candidate of the new cycle ($p_1$) must occur strictly after the CHOCH confirmation bar ($c_2$) in chronological sequence. Specifically, in chronological candle positions:
   $$\text{position}(p_1) \ge \text{position}(c_2) + 1$$
   Candles that formed prior to or at $c_2$ cannot be recycled to claim an instant pullback in the new direction.

## Specification

- Bearish CHOCH confirmed at chronological candle index: `9` ($c_2$).
- Active Point 3 original candle index: `5`.
- Expected New Cycle State:
  - `direction = "DOWNWARD"`
  - `search_start_candle_idx = 5`
  - `first_pullback_min_candidate_idx = 10` ($p_1 \ge 10$)
