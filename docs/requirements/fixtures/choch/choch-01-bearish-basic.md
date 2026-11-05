# Fixture CHOCH-01: Bearish CHOCH Basic (End-to-End Confirmation)

- **Source Authority**: `docs/strategy/Choch.pdf` (Bearish CHOCH), with `docs/strategy/extracted/choch.md` (Version 2, 13 October 2026) as a review transcription aid; underlying MSM foundation from `Market Structure Marking.docx` Section 3 (Upward Algorithm); approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-03, OPEN-04, OPEN-08, OPEN-09, OPEN-10).
- **Fixture Category**: `end_to_end_msm_derived`, `source_settled`
- **Starting Structure**: Upward structure with Last Support at `1.105` (chronological index 4), Confirmed High at `1.135` (chronological index 1), and Tentative Point 3 at `1.155` (chronological index 5, identified at index 7).
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_bearish_basic_end_to_end`)

## OHLC Dataset

| Index | Timestamp (UTC) | Open | High | Low | Close | Role / Behavior |
|---|---|---|---|---|---|---|
| 0 | 2026-10-01 00:00 | 1.100 | 1.110 | 1.095 | 1.105 | Initial cycle start |
| 1 | 2026-10-01 04:00 | 1.105 | 1.140 | 1.102 | 1.135 | Confirmed High candidate (UB = 1.135, High = 1.140, LB = 1.105) |
| 2 | 2026-10-01 08:00 | 1.135 | 1.136 | 1.115 | 1.120 | Pullback candle 1 (Low = 1.115, LB = 1.120) |
| 3 | 2026-10-01 12:00 | 1.120 | 1.122 | 1.100 | 1.105 | Pullback candle 2 (`close < low[2]`) -> Tentative High identified at 1 (LB = 1.105) |
| 4 | 2026-10-01 16:00 | 1.105 | 1.150 | 1.104 | 1.145 | Continuation break (`close > 1.135`). Confirmed Low search window is `[1, 4]`. Minimum LB `1.105` is tied at candles 1, 3, 4; latest-candle tie-breaker selects **Candle 4**! (Low = 1.104, LB = 1.105) |
| 5 | 2026-10-01 20:00 | 1.145 | 1.160 | 1.142 | 1.155 | Point 3 peak (UB = 1.155, High = 1.160) |
| 6 | 2026-10-02 00:00 | 1.155 | 1.156 | 1.135 | 1.140 | Pullback 1 after Point 3 (Low = 1.135) |
| 7 | 2026-10-02 04:00 | 1.140 | 1.142 | 1.120 | 1.125 | Pullback 2 (`close < low[6]`) -> Point 3 identified as active upon completion |
| 8 | 2026-10-02 08:00 | 1.125 | 1.128 | 1.090 | 1.095 | First qualifying close below Last Support (Close = 1.095 < 1.105) |
| 9 | 2026-10-02 12:00 | 1.095 | 1.098 | 1.080 | 1.085 | Second qualifying close below Last Support (Close = 1.085 < 1.105) |

## Evaluation Walkthrough

1. **MSM Prerequisite Verification (Cross-Checked via MSMEngine)**:
   - MSM Structure: `UPWARD`.
   - First pair confirms at candle 4:
     - Confirmed High: Index `1`, Upper Body edge `1.135` (`candle_time = 2026-10-01 04:00 UTC`).
     - Confirmed Low (Last Support): Evaluated over inclusive window `[1, 4]`. Lower body edges are: candle 1 (1.105), candle 2 (1.120), candle 3 (1.105), candle 4 (1.105). The minimum value `1.105` is tied across candles `[1, 3, 4]`. Section 2.4 selects the latest candle: **Index 4** (`candle_time = 2026-10-01 16:00 UTC`, `low = 1.104, LB = 1.105`).
   - Point 3 Candidate: Index `5` has Upper Body edge `1.155`. Valid 2-candle pullback forms at chronological indices `6` and `7` (`close[7] < low[6]`), identifying Point 3 as active upon completion of index `7`.

2. **CHOCH Confirmation Sequence**:
   - Candle `8` completes at `2026-10-02 12:00 UTC`: `Close = 1.095 < 1.105` (Strict inequality satisfied, Close 1 recorded). Occurs strictly after Point 3 identification ($8 \ge 7 + 1$).
   - Candle `9` completes at `2026-10-02 16:00 UTC`: `Close = 1.085 < 1.105` (Strict inequality satisfied, Close 2 at the immediate next chronological completed position).
   - **Confirmation Event**: Bearish CHOCH confirmed upon completion of Candle `9` (`confirmed_at = 2026-10-02 16:00 UTC`).

3. **Zone Construction**:
   - **Support-Become-Resistance (SBR)**: Derived from the broken Last Support candle (**Index 4**).
     - Lower boundary: `low[4] = 1.104`
     - Upper boundary: `LB[4] = min(open[4], close[4]) = 1.105`
     - Span: `[1.104, 1.105]`
   - **Quasimodo Level / A+ (QML / A+)**: Derived from the preceding Confirmed High candle (**Index 1**).
     - Lower boundary: `UB[1] = max(open[1], close[1]) = 1.135`
     - Upper boundary: `high[1] = 1.140`
     - Span: `[1.135, 1.140]`
   - **Double Top**: Derived from the active Tentative Point 3 original candle (**Index 5**).
     - Lower boundary: `UB[5] = max(open[5], close[5]) = 1.155`
     - Upper boundary: `high[5] = 1.160`
     - Span: `[1.155, 1.160]`

4. **New Cycle State**:
   - Previous upward cycle terminated.
   - New Direction: `DOWNWARD`.
   - New Cycle Search Reference: Index `5` (`2026-10-01 20:00 UTC`).
   - First subsequent downward pullback search (`p1`): Must be strictly after confirmation candle `9` in chronological position ($p_1 \ge 10$).
