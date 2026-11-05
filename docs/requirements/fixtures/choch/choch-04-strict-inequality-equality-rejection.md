# Fixture CHOCH-04: Strict Inequality (Equality Rejection)

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 3.1 & `docs/requirements/approved-clarifications.md` (OPEN-01, OPEN-03)
- **Starting Structure**: Upward structure with Last Support at `1.105` and active Point 3 at `1.155`.
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_equality_rejected_on_first_or_second_close`)

## Description
A qualifying break requires strict inequality:
- Bearish: $\text{close} < \text{last\_support}$ (exact equality $\text{close} == \text{last\_support}$ fails).
- Bullish: $\text{close} > \text{last\_resistance}$ (exact equality $\text{close} == \text{last\_resistance}$ fails).

Equality on either the first candle ($c_1$) or the second candle ($c_2$) invalidates confirmation.

## Test Cases

### Case A: Equality on First Candle ($c_1$)
- Candle $c_1$: `Close = 1.105 == 1.105` (Last Support).
- Candle $c_2$: `Close = 1.090 < 1.105`.
- Evaluation: $c_1$ fails strict inequality; no qualifying first close. $c_2$ is treated as a candidate first close, not second.
- Result: `confirmed = false`, `reason = "EQUALITY_ON_FIRST_CLOSE"`.

### Case B: Equality on Second Candle ($c_2$)
- Candle $c_1$: `Close = 1.095 < 1.105` (Qualifies as first close).
- Candle $c_2$: `Close = 1.105 == 1.105` (Fails strict inequality).
- Evaluation: $c_2$ fails strict inequality; consecutive count resets.
- Result: `confirmed = false`, `reason = "EQUALITY_ON_SECOND_CLOSE"`.
