# Fixture CHOCH-06: Wick Crossing Without Qualifying Close Rejection

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 3.1 & `docs/requirements/approved-clarifications.md` (OPEN-01, OPEN-03)
- **Starting Structure**: Upward structure with Last Support at `1.105` and active Point 3 at `1.155`.
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_wick_crossing_without_qualifying_close_rejected`)

## Description
A candle whose wick crosses beyond the broken level while its closing price remains inside or on the level does not qualify. The strategy strictly requires closing price breaks.

## Candidate Candles

| Index | Low | Close | Last Support | Evaluation |
|---|---|---|---|---|
| 8 | 1.080 | 1.106 | 1.105 | Wick pierces level (`low < 1.105`), but `close >= 1.105`. Fails. |
| 9 | 1.085 | 1.107 | 1.105 | Wick pierces level (`low < 1.105`), but `close >= 1.105`. Fails. |

## Expected Behavior
- Neither candle qualifies as a closing break.
- Pending qualifying close count remains 0.
- Result: `confirmed = false`, `reason = "WICK_CROSSING_ONLY_CLOSE_FAILED"`.
