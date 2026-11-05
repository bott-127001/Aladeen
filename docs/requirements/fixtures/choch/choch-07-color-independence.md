# Fixture CHOCH-07: Candle Color Independence

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 3.1 & `docs/requirements/approved-clarifications.md` (OPEN-01, OPEN-04)
- **Starting Structure**: Upward structure with Last Support at `1.105` and active Point 3 at `1.155`.
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_qualifying_closes_with_mixed_candle_colors_confirmed`)

## Description
The 2 consecutive qualifying closes rule is strictly a price-level test against Last Support / Last Resistance, NOT a candle-color test. Green (bullish) candles can qualify for Bearish CHOCH provided their completed close is strictly below Last Support, and red (bearish) candles can qualify for Bullish CHOCH provided their completed close is strictly above Last Resistance.

## Candidate Candles

| Index | Open | Close | Color | Evaluated against Last Support (1.105) |
|---|---|---|---|---|
| 8 | 1.090 | 1.098 | Green (`close > open`) | `close = 1.098 < 1.105` -> Qualifies as $c_1$ |
| 9 | 1.100 | 1.085 | Red (`close < open`) | `close = 1.085 < 1.105` -> Qualifies as $c_2$ |

## Expected Behavior
- Both candles close strictly below Last Support.
- Candle color is ignored.
- Result: `confirmed = true`, `type = "BEARISH_CHOCH"`.
