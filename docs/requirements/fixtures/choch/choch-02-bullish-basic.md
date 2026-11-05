# Fixture CHOCH-02: Bullish CHOCH Basic (End-to-End Confirmation)

- **Source Authority**: `docs/strategy/Choch.pdf` (Bullish CHOCH), with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; underlying MSM foundation from `Market Structure Marking.docx` Section 4 (Downward Algorithm); approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-03, OPEN-04, OPEN-08, OPEN-09, OPEN-10).
- **Fixture Category**: `end_to_end_msm_derived`, `source_settled`
- **Starting Structure**: Downward structure with Last Resistance at `1.240` (chronological index 3), Confirmed Low at `1.215` (chronological index 1), and Tentative Point 3 at `1.185` (chronological index 5, identified at index 7).
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_bullish_basic_end_to_end`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Behavior |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 1.250 | 1.255 | 1.240 | 1.245 | Initial downward cycle start |
| 1 | 2026-10-01 04:00 | 1.245 | 1.248 | 1.210 | 1.215 | Confirmed Low candidate (LB = 1.215, Low = 1.210) |
| 2 | 2026-10-01 08:00 | 1.215 | 1.235 | 1.212 | 1.230 | Pullback candle 1 (High = 1.235) |
| 3 | 2026-10-01 12:00 | 1.230 | 1.242 | 1.228 | 1.240 | Confirmed High / Last Resistance (UB = 1.240, High = 1.242) |
| 4 | 2026-10-01 16:00 | 1.240 | 1.241 | 1.200 | 1.205 | Continuation break of Confirmed Low (Close = 1.205 < 1.215) |
| 5 | 2026-10-01 20:00 | 1.205 | 1.208 | 1.180 | 1.185 | Point 3 trough (LB = 1.185, Low = 1.180) |
| 6 | 2026-10-02 00:00 | 1.185 | 1.205 | 1.184 | 1.200 | Pullback 1 after Point 3 (High = 1.205) |
| 7 | 2026-10-02 04:00 | 1.200 | 1.220 | 1.198 | 1.215 | Pullback 2 (Close = 1.215 > 1.205) -> Point 3 active |
| 8 | 2026-10-02 08:00 | 1.215 | 1.248 | 1.214 | 1.245 | First qualifying close above Last Resistance (Close = 1.245 > 1.240) |
| 9 | 2026-10-02 12:00 | 1.245 | 1.258 | 1.242 | 1.252 | Second qualifying close above Last Resistance (Close = 1.252 > 1.240) |

## Evaluation Walkthrough

1. **Prerequisite Verification**:
   - MSM Structure: `DOWNWARD`.
   - Last Resistance: Confirmed at chronological index `3` with Upper Body edge `1.240`.
   - Confirmed Low: Confirmed at chronological index `1` with Lower Body edge `1.215`.
   - Point 3 Candidate: Index `5` has Lower Body edge `1.185`. Valid 2-candle upward pullback formed at chronological indices `6` and `7` (`close[7] > high[6]`), identifying Point 3 as active upon completion of index `7`.

2. **CHOCH Confirmation Sequence**:
   - Candle `8` completes at `2026-10-02 12:00 UTC`: `Close = 1.245 > 1.240` (Strict inequality satisfied, Close 1 recorded). Occurs strictly after Point 3 identification ($8 \ge 7 + 1$).
   - Candle `9` completes at `2026-10-02 16:00 UTC`: `Close = 1.252 > 1.240` (Strict inequality satisfied, Close 2 at immediate next chronological position).
   - **Confirmation Event**: Bullish CHOCH confirmed upon completion of Candle `9` (`confirmed_at = 2026-10-02 16:00 UTC`).

3. **Zone Construction**:
   - **Resistance-Become-Support (RBS)**: Derived from the broken Last Resistance candle (Index `3`).
     - Lower boundary: `UB[3] = max(open[3], close[3]) = 1.240`
     - Upper boundary: `high[3] = 1.242`
     - Span: `[1.240, 1.242]`
   - **Quasimodo Level / A+ (QML / A+)**: Derived from the preceding Confirmed Low candle (Index `1`).
     - Lower boundary: `low[1] = 1.210`
     - Upper boundary: `LB[1] = min(open[1], close[1]) = 1.215`
     - Span: `[1.210, 1.215]`
   - **Double Bottom**: Derived from the active Tentative Point 3 original candle (Index `5`).
     - Lower boundary: `low[5] = 1.180`
     - Upper boundary: `LB[5] = min(open[5], close[5]) = 1.185`
     - Span: `[1.180, 1.185]`

4. **New Cycle State**:
   - Previous downward cycle terminated.
   - New Direction: `UPWARD`.
   - New Cycle Search Reference: Index `5` (`2026-10-01 20:00 UTC`).
   - First subsequent upward pullback search (`p1`): Must be strictly after confirmation candle `9` in chronological position ($p_1 \ge 10$).
