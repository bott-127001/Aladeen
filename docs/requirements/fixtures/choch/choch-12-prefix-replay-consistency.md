# Fixture CHOCH-12: Prefix Replay Consistency

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` & `docs/requirements/approved-clarifications.md`
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_prefix_replay_consistency`)

## Description
CHOCH evaluation is strictly deterministic and causal:
- Evaluating an OHLC candle sequence sliced to length $N$ (e.g. `candles[0:10]`) must yield the exact same confirmed CHOCH state, timestamps, levels, and zone geometries as evaluating an extended series `candles[0:15]` up to index $N-1$.
- No forward-looking information (lookahead) can influence past CHOCH states.
- Historical CHOCH events remain immutable once confirmed.

## Expected Behavior
- Any historical slice prefix replay produces identical results to full replay evaluated at that historical point in time.
- Invariant: `PREFIX_REPLAY_IDENTICAL`.
