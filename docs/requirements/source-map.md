# Source Map — Strategy Module Requirements

> [!NOTE]
> **Reconciliation Status (Updated 2026-11-05)**:
> Later user-approved clarifications from the TopG project artifact (*Aladin TopG Dashboard — Revised Contract*, 4 November 2026) have been recorded in [`approved-clarifications.md`](file:///docs/requirements/approved-clarifications.md).
> Key reconciliations:
> - **EMPTY RANGE**: Reconciled. When a pullback leaves an empty search range, skip that pullback pair and continue searching from the original starting candle reference.
> - **OPEN-01**: Trend status is display-only and computed separately from marking direction.
> - **OPEN-08**: Engine instances operate independently without silent state inheritance.
> - **OPEN-10**: Timeframe boundaries are native MT5 feed timestamps normalized to UTC.
> Strategy engine implementation remains strictly gated pending individual module acceptance specifications.

---

## 1. MSM — Market Structure Marking

### Source Sections
- Original Authority: `TopG.pdf` pages 1–8
- Strategy Document: `docs/strategy/Market Structure Marking.docx` — Sections 1–8
- Transcription: `docs/strategy/extracted/market-structure-marking.md`
- Approved Clarifications: `docs/requirements/approved-clarifications.md` (EMPTY RANGE, OPEN-01, OPEN-08, OPEN-10)

### Inputs and Configuration
- **User-selected starting candle**: Mandatory manual start. Must be a verified completed candle; absent or actively forming starts are strictly rejected.
- **User-selected starting direction**: Upward or downward.
- **Timeframe**: Timeframe-agnostic engine. While originally illustrated on H4 and D1, the shared MSM engine applies to any configured timeframe required by composite strategy roles (D1, H4, H1 in main/TJL/ISS, and M5, M1 in confirmation detection).
- **Candle data**: Validated contract DataFrame (`open`, `high`, `low`, `close`, UTC DatetimeIndex, completed candles only).

### Outputs
- **Tentative highs and lows**: Point index, timestamp, and body-edge price.
- **Confirmed highs and lows**: Point index, timestamp, and body-edge price.
- **Last support** (latest confirmed low in upward structure).
- **Last resistance** (latest confirmed high in downward structure).
- **Display-only Trend Status**: "Marking [direction] structure" / "Upward trend" / "Downward trend" / "Trend not confirmed". (Display-only per OPEN-01; does not alter engine direction).
- **History of confirmed levels**.

### State Transitions and Dependencies
1. **Idle → Searching for pullback**: Initialized with validated start candle and direction.
2. **Searching for pullback → Tentative level identified**: Valid two-candle pullback found with non-empty search range.
3. **Tentative level identified → Waiting for closing break**: Tentative high/low marked.
4. **Waiting for closing break → Confirmed pair**: Candle closes strictly beyond tentative level.
5. **Confirmed pair → Searching for next pullback**: Search-start advances to candle containing the newly confirmed opposite level.
6. Trend comparison requires ≥ 2 completed confirmed pairs.

### Explicit Rules
- **Body edges**: Upper = `max(open, close)`, Lower = `min(open, close)`. All tentative and confirmed swings use body edges.
- **Pullback (upward)**: 2 consecutive red candles (`close < open`), where 2nd candle closes strictly below 1st candle's bottom wick tip (`close_2 < low_1`).
- **Pullback (downward)**: 2 consecutive green candles (`close > open`), where 2nd candle closes strictly above 1st candle's top wick tip (`close_2 > high_1`).
- **Tentative level search range**: Inclusive of search-start, strictly exclusive of both pullback candles: `[search_start, pullback_candle_1)`.
- **Opposite level search range**: Inclusive of both endpoints from confirmed tentative candle through closing-break candle: `[tentative_candle, break_candle]`.
- **Tied body edges**: Latest candle selected.
- **Strict comparisons**: Equality never satisfies pullback or break conditions (`>` or `<`).
- **Flat candles** (`open == close`): Neither red nor green. Interrupts a pullback run; eligible for body-edge searches and closing breaks.
- **Break candle colour**: Immaterial.
- **No independent cycle**: While waiting for a closing break, no new tentative point can be formed.

### Reconciled Decisions & Clarifications
- **Empty search range (Section 7)**: **RECONCILED**. If the starting candle is itself the first pullback candle, the range `[start, pullback_1)` is empty. The engine skips this pullback pair and continues searching forward from the original start candle.
- **Trend status role (Section 5)**: **RECONCILED**. Display-only (OPEN-01). Does not trigger direction changes or trade execution.
- **Timeframe scope (Section 1)**: General shared engine; not artificially constrained to H4/D1 when composite modules (ISS, TJL, MTF) configure H1, M5, or M1.

### Ambiguities — Detailed Implementation Rules to Reconcile
1. None for MSM baseline. All core marking rules and the empty-range edge case are formally reconciled.

### Candidate Test Scenarios
1. Basic upward cycle: green run → 2 red pullback → tentative high → close above → confirmed pair.
2. Basic downward cycle: red run → 2 green pullback → tentative low → close below → confirmed pair.
3. Failed pullback: 2nd red closes above or equal to 1st wick tip → skip pair and continue.
4. Flat candle interruption: green → flat → red → red does not qualify as a 2-red run.
5. Tied body edges: latest candle selected in tentative and confirmed searches.
6. Strict equality rejection: close exactly equal to wick tip or tentative level does not qualify.
7. Empty range handling: starting candle is pullback candle 1 → skipped cleanly; original reference retained.
8. Trend status evaluation: 2 confirmed pairs strictly higher -> Upward trend; tie -> Trend not confirmed.

---

## 2. CHOCH — Change of Character

### Source Sections
- Original Authority: `TopG.pdf` pages 9–12
- Strategy Document: `docs/strategy/Choch.pdf` — Sections 1–10
- Transcription: `docs/strategy/extracted/choch.md`
- Approved Clarifications: `docs/requirements/approved-clarifications.md` (OPEN-03, OPEN-04, OPEN-08, OPEN-10, OPEN-11)

### Inputs and Configuration
- Active marking direction (from MSM).
- Latest confirmed support / resistance prices and source candles (from MSM).
- Active tentative point 3 (from current unconfirmed MSM cycle).
- Completed candle data on source timeframe (e.g. H4, D1) or confirmation timeframe (H1, M5, M1).

### Outputs
- CHOCH confirmed signal (bearish or bullish).
- Three structural zones:
  - Bearish: SBR (confirmed low / last support), QML/A+ (confirmed high), Double top (tentative point 3).
  - Bullish: RBS (confirmed high / last resistance), QML/A+ (confirmed low), Double bottom (tentative point 3).
- Zone geometries: `[body_edge, wick_tip]` or single price line when wick is zero.
- New reference candle and inverted direction for MSM restart.

### State Transitions and Dependencies
1. **Monitoring**: Point 3 active; monitoring for break of last support/resistance.
2. **First qualifying close**: Candle closes strictly beyond support/resistance in reversal direction.
3. **Confirmed CHOCH**: Immediately next candle also closes strictly beyond in reversal direction (2 consecutive closes).
4. **Failed pair**: Next candle does not close beyond level → resets consecutive close counter to 0.
5. **Restart**: Point 3 candle becomes new reference candle; marking restarts in inverted direction.

### Explicit Rules
- Bearish CHOCH: 2 consecutive closes strictly below last support (`close < support`).
- Bullish CHOCH: 2 consecutive closes strictly above last resistance (`close > resistance`).
- Non-consecutive closes cannot combine.
- Point 3 must exist prior to the first qualifying close. If the MSM cycle completes normally (break confirms point 3), point 3 is consumed and CHOCH cannot form until a new tentative point 3 forms.
- Reversal restart: Pullback search in new direction starts only after the CHOCH confirmation candle.

### Reconciled Decisions & Clarifications
- **Invalidation Precedence (OPEN-03)**: At a shared close where a level is invalidated and a potential entry appears, source invalidation executes first.
- **Candle Interval & Order (OPEN-04)**: Candle boundaries are `[open, close)`. A confirmation occurring at the close cannot claim earlier intra-candle wicks.

### Ambiguities — Detailed Rules Pending Specification Before Implementation
1. Lifecycle of point 3 if a break and new pullback occur in rapid succession before second CHOCH close.

---

## 3. ISS — Internal Structure Shift

### Source Sections
- Original Authority: `TopG.pdf` pages 15–16
- Strategy Document: `docs/strategy/ISS.pdf` — Sections 1–14
- Transcription: `docs/strategy/extracted/iss.md`
- Approved Clarifications: `docs/requirements/approved-clarifications.md` (EMPTY RANGE, OPEN-03, OPEN-04, OPEN-07, OPEN-08)

### Inputs and Configuration
- Main level 2 (confirmed low/high from MSM) — price and source candle.
- Main level 3 (active tentative high/low from MSM) — price and source candle.
- Fixed boundary: inclusive interval `[min(L2, L3), max(L2, L3)]` body-edge prices.
- Candle data on H1 timeframe (or lower confirmation timeframe when configured).

### Outputs
- ISS confirmed signal.
- Two structural zones:
  - Bearish main: Level 3 = Internal CH2 (RBS), Level 4/A+ = Internal CL2 (buying A+).
  - Bullish main: Level 3 = Internal CL2 (SBR), Level 4/A+ = Internal CH2 (selling A+).
- ISS lifecycle state: Searching / Confirmed / Rejected / Tracking-Only.

### State Transitions and Dependencies
1. **Eligible search**: Main level 3 identified → internal MSM starts in opposite direction within fixed boundaries.
2. **Building internal structure**: Accumulating 5 internal swing points (CH1, CL1, CH2, CL2, tentative).
3. **Confirmed ISS**: 5th point identified, all 5 point prices inside boundary, completion close inside boundary.
4. **Out-of-bounds rejection**: Any marked internal level outside boundary → permanently rejected for that level 3.
5. **Main continuation cancellation**: Main break confirms level 3 before internal 5-point completion → cancel ISS.
6. **Main CHOCH cancellation**: Main structure CHOCH cancels active ISS search.

### Explicit Rules
- Exactly 5 internal points (2 confirmed highs, 2 confirmed lows, 1 tentative).
- Uses standard MSM rules for internal swings.
- Boundary check evaluates marked swing prices, not intervening wick excursions.
- Boundary equality is permitted (unlike strict swing break rules).
- Confirmed on completion of the 5th point pullback, not at continuation break.

### Reconciled Decisions & Clarifications
- **Consolidated Confirmation (OPEN-07)**: If an entry has both CHOCH and ISS confirmation, record both IDs on one entry without duplicate execution.
- **Fail-Closed Principle**: Missing evidence blocks only the affected transition, never independent state.

---

## 4. TJL — Trend Joining Level

### Source Sections
- Original Authority: `TopG.pdf` pages 17–18
- Strategy Document: `docs/strategy/TJL.pdf` — Sections 1–9
- Transcription: `docs/strategy/extracted/tjl.md`
- Approved Clarifications: `docs/requirements/approved-clarifications.md` (OPEN-02, OPEN-05, OPEN-08, OPEN-10)

### Inputs and Configuration
- Confirmed highs and lows from MSM (evaluated on D1, H4, H1).
- Main structure direction.

### Outputs
- **TJL1 label & zone**: Confirmed high in bullish / confirmed low in bearish.
- **TJL2 / A+ label & zone**: Confirmed low (LSM) in bullish / confirmed high (LRM) in bearish.
- Zone boundaries: `[body_edge, wick_tip]`.

### Base Module Rules vs. MTF Eligibility Overrides
- **Base TJL Module (`TJL.pdf`)**:
  - Serves strictly as a labeling and zone definition layer on top of confirmed MSM swings.
  - In the base module description, only the latest TJL2 / A+ is designated as trading-eligible; TJL1 is labeled non-trading-eligible.
- **MTF Module Override (`MTF-Analysis.pdf` Section 13)**:
  - Under MTF Multi-Timeframe Entry Confirmation, **both TJL1 and TJL2 are explicitly eligible for tap activation and confirmation search**.
  - TJL1 does NOT require a breakout-retest; it activates on tap under identical confirmation rules.
  - In competing simultaneous confirmation ties between TJL1 and TJL2 from the same source timeframe, TJL2/A+ takes precedence.

### Reconciled Decisions & Clarifications
- **Lifecycle Timing (OPEN-02)**: TJL labels appear at t1; active trading set updates only at t2. Detailed t1/t2 timing criteria must be specified prior to TJL coding.
- **Out-of-zone Cancellation Rearming (OPEN-05)**: If cancelled while price is already outside the zone, the next touch is rearmed.

---

## 5. MTF — Multi-Timeframe Entry Confirmation

### Source Sections
- Original Authority: `MTF-Analysis.pdf` — Sections 1–13 (complete document)
- Baseline: `Entry_and_Confirmation_New_Rules.pdf`
- Approved Clarifications: `docs/requirements/approved-clarifications.md` (OPEN-02 through OPEN-12)

### Inputs and Configuration
- Active TJL zones on D1, H4, H1.
- Candle data on D1, H4, H1, M5, M1.
- Mapped confirmation detection (H1 for D1; M5 for H4; M1 for H1).

### Outputs
- Zone activations (on physical wick touch).
- Entry signals (on fresh lower-timeframe confirmation close).
- Level usage state (Available, Activated, Used, Cancelled).

### Explicit Rules & Reconciliations
- **Single Price Basis (OPEN-06)**: Touch requires physical print inside inclusive zone `[lower, upper]`; no path interpolation.
- **Fresh Transition Requirement**: Confirmation must be a fresh structural transition occurring on or after the tap candle.
- **One Trade Per Level**: An entry signal consumes the level (`Used`). A used level never reactivates.
- **Conflict Resolution**: Earliest timestamp wins; tie-breakers: lower timeframe wins (M1 > M5 > H1); same-timeframe TJL2 wins over TJL1.
- **No Position Gating (OPEN-11)**: All conceptual signals are listed chronologically without trade/execution filtering.

### Distinct Scope Boundaries (Deliberately Out of Scope)
- Order execution, live broker placement, slippage handling, and stop-loss/take-profit calculation are strictly outside application scope. They are not strategy ambiguities.

---

## Cross-Module Architecture & Precedence

```
┌─────────────────────────────────────────────────────────────┐
│                      Candle Data Feed                       │
│           (Native MT5 UTC Timestamps, Contract Validated)   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             MSM (Market Structure Marking Engine)           │
│  - Timeframe-agnostic (D1, H4, H1, M5, M1)                  │
│  - Reconciled Empty-Range Skip & Display-Only Trend Status  │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────────┐┌──────────────────────────────┐
│       CHOCH Detection        ││             TJL              │
│  - Point 3 monitoring        ││  - Structural zone labeling  │
│  - 2 consecutive closes      ││  - t1 identification timing  │
└──────────────┬───────────────┘└─────────────┬────────────────┘
               │                              │
               ▼                              │
┌──────────────────────────────┐              │
│        ISS Detection         │              │
│  - 5-point internal swings   │              │
└──────────────┬───────────────┘              │
               │                              │
               └──────────────┬───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│             MTF Multi-Timeframe Confirmation                │
│  - Physical touch activation (OPEN-06)                      │
│  - Fresh lower-TF confirmation (CHOCH / ISS)                │
│  - Invalidation precedence before entry (OPEN-03)           │
│  - Chronological signal generation without position gating  │
└─────────────────────────────────────────────────────────────┘
```
