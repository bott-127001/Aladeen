# Fixture CHOCH-02: Bullish CHOCH Basic (End-to-End Confirmation)

- **Source Authority**: `docs/strategy/Choch.pdf` (Bullish CHOCH), with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; underlying MSM foundation from `Market Structure Marking.docx` Section 4 (Downward Algorithm); approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-03, OPEN-04, OPEN-08, OPEN-09, OPEN-10).
- **Fixture Category**: `end_to_end_msm_derived`, `source_settled`
- **Starting Structure**: Downward structure with Last Resistance at `1.245` (chronological index 1), Confirmed Low at `1.215` (chronological index 1), and Tentative Point 3 at `1.185` (chronological index 5, identified at index 7).
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_bullish_basic_end_to_end`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Behavior |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 1.250 | 1.255 | 1.240 | 1.245 | Initial downward cycle start |
| 1 | 2026-10-01 04:00 | 1.245 | 1.248 | 1.210 | 1.215 | Confirmed Low candidate (LB = 1.215, Low = 1.210, UB = 1.245, High = 1.248) |
| 2 | 2026-10-01 08:00 | 1.215 | 1.235 | 1.212 | 1.230 | Pullback candle 1 (High = 1.235, UB = 1.230) |
| 3 | 2026-10-01 12:00 | 1.230 | 1.242 | 1.228 | 1.240 | Pullback candle 2 (`close > high[2]`) -> Tentative Low identified at 1 (UB = 1.240) |
| 4 | 2026-10-01 16:00 | 1.240 | 1.241 | 1.200 | 1.205 | Continuation break (`close < 1.215`). Confirmed High search window is `[1, 4]`. Maximum UB is **1.245 at Candle 1** (UB = 1.245, High = 1.248) -> Last Resistance! |
| 5 | 2026-10-01 20:00 | 1.205 | 1.208 | 1.180 | 1.185 | Point 3 trough (LB = 1.185, Low = 1.180) |
| 6 | 2026-10-02 00:00 | 1.185 | 1.205 | 1.184 | 1.200 | Pullback 1 after Point 3 (High = 1.205) |
| 7 | 2026-10-02 04:00 | 1.200 | 1.220 | 1.198 | 1.215 | Pullback 2 (`close > high[6]`) -> Point 3 active upon completion |
| 8 | 2026-10-02 08:00 | 1.215 | 1.248 | 1.214 | 1.245 | Close = 1.245 == 1.245 (Last Resistance). **Exact equality fails closed!** Does NOT qualify. |
| 9 | 2026-10-02 12:00 | 1.245 | 1.258 | 1.242 | 1.252 | First qualifying close strictly above Last Resistance (Close = 1.252 > 1.245, $c_1$) |
| 10 | 2026-10-02 16:00 | 1.252 | 1.265 | 1.250 | 1.260 | Second consecutive qualifying close strictly above Last Resistance (Close = 1.260 > 1.245, $c_2$) |

## Evaluation Walkthrough

1. **MSM Prerequisite Verification (Cross-Checked via MSMEngine)**:
   - MSM Structure: `DOWNWARD`.
   - First pair confirms at candle 4:
     - Confirmed Low: Index `1`, Lower Body edge `1.215` (`candle_time = 2026-10-01 04:00 UTC`).
     - Confirmed High (Last Resistance): Evaluated over inclusive window `[1, 4]`. Upper body edges are: candle 1 (1.245), candle 2 (1.230), candle 3 (1.240), candle 4 (1.240). Maximum UB is `1.245` at **Index 1** (`candle_time = 2026-10-01 04:00 UTC`, `UB = 1.245, High = 1.248`).
   - Point 3 Candidate: Index `5` has Lower Body edge `1.185`. Valid 2-candle upward pullback forms at chronological indices `6` and `7` (`close[7] > high[6]`), identifying Point 3 as active upon completion of index `7`.

2. **CHOCH Confirmation Sequence**:
   - Candle `8` completes at `2026-10-02 12:00 UTC`: `Close = 1.245 == 1.245` (Exact equality rejected; does not qualify).
   - Candle `9` completes at `2026-10-02 16:00 UTC`: `Close = 1.252 > 1.245` (Strict inequality satisfied, Close 1 recorded).
   - Candle `10` completes at `2026-10-02 20:00 UTC`: `Close = 1.260 > 1.245` (Strict inequality satisfied, Close 2 consecutive).
   - **Confirmation Event**: Bullish CHOCH confirmed upon completion of Candle `10` (`confirmed_at = 2026-10-02 20:00 UTC`).

3. **Zone Construction**:
   - **Resistance-Become-Support (RBS)**: Derived from the broken Last Resistance candle (**Index 1**).
     - Lower boundary: `UB[1] = max(open[1], close[1]) = 1.245`
     - Upper boundary: `high[1] = 1.248`
     - Span: `[1.245, 1.248]`
   - **Quasimodo Level / A+ (QML / A+)**: Derived from the preceding Confirmed Low candle (**Index 1**).
     - Lower boundary: `low[1] = 1.210`
     - Upper boundary: `LB[1] = min(open[1], close[1]) = 1.215`
     - Span: `[1.210, 1.215]`
   - **Double Bottom**: Derived from the active Tentative Point 3 original candle (**Index 5**).
     - Lower boundary: `low[5] = 1.180`
     - Upper boundary: `LB[5] = min(open[5], close[5]) = 1.185`
     - Span: `[1.180, 1.185]`

4. **New Cycle State**:
   - Previous downward cycle terminated.
   - New Direction: `UPWARD`.
   - New Cycle Search Reference: Index `5` (`2026-10-01 20:00 UTC`).
   - First subsequent upward pullback search (`p1`): Must be strictly after confirmation candle `10` in chronological position ($p_1 \ge 11$).
