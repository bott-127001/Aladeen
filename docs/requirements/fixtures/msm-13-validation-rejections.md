# Fixture MSM-13: Validation Rejection Specifications

- **Source Section**: `Market Structure Marking.docx` Section 1 & `approved-clarifications.md` (OPEN-08)
- **Machine-Readable Target**: `tests/fixtures/msm_acceptance.json` (`MSM-13A`, `MSM-13B`)

## Case A: Start Candle Not in Index (`MSM-13A`)
- **Input Dataset**: Timestamps `[2026-10-01 00:00, 2026-10-01 04:00]`
- **Selected `start_candle_time`**: `2026-10-01 08:00` (absent)
- **Expected Result**: Initialization raises:
  `ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")`

## Case B: Start Candle is Currently Forming (`MSM-13B`)
- **Input Dataset**: Candle `2026-10-01 04:00` has `is_forming == True` (or `bar_status != CONFIRMED_COMPLETED`)
- **Selected `start_candle_time`**: `2026-10-01 04:00`
- **Expected Result**: Initialization raises:
  `ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")`
