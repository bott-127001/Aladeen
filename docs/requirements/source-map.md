# Source Map — Strategy Module Requirements

> [!IMPORTANT]
> These documents may not include later user-approved clarifications. Document-level ambiguities are labeled **"pending reconciliation with approved clarifications"**, not as permission to invent defaults. Do not use old dashboard code, Pine scripts, or TopG_Implementation.pdf as strategy authority.

---

## 1. MSM — Market Structure Marking

### Source Sections
- `Market Structure Marking.docx` — Sections 1–8 (complete document)
- Original authority: TopG.pdf pages 1–8

### Inputs and Configuration
- **User-selected starting candle** (manual, not automatic)
- **User-selected starting direction**: upward or downward
- **Timeframe**: H4 or D1 (applied separately)
- **Candle data**: open, high, low, close for each completed candle

### Outputs
- Tentative highs and lows (with source candle index)
- Confirmed highs and lows (with source candle index and body-edge price)
- Last support (latest confirmed low in upward marking)
- Last resistance (latest confirmed high in downward marking)
- Trend status: "Marking [direction] structure" / "Upward trend" / "Downward trend" / "Trend not confirmed"
- History of all confirmed levels

### State Transitions and Dependencies
1. **Idle → Searching for pullback**: user selects starting candle and direction
2. **Searching for pullback → Tentative level identified**: valid two-candle pullback found
3. **Tentative level identified → Waiting for closing break**: tentative high/low marked
4. **Waiting for closing break → Confirmed pair**: candle closes strictly beyond tentative level
5. **Confirmed pair → Searching for next pullback**: search-start moves to confirmed opposite level candle
6. Trend comparison requires ≥ 2 completed pairs

### Explicit Rules
- Body edges: upper = max(open, close), lower = min(open, close)
- Pullback (upward): 2 consecutive red candles, 2nd closes strictly below 1st's bottom wick tip
- Pullback (downward): 2 consecutive green candles, 2nd closes strictly above 1st's top wick tip
- Tentative level search excludes both pullback candles; includes search-start
- Opposite level search includes both endpoints (tentative level candle through break candle)
- Tied body edges → select latest candle
- Strict comparisons only; equality never satisfies
- Flat candles (open = close) interrupt colour runs but remain eligible for body-edge searches
- Break candle colour does not matter
- No independent cycle while waiting for a closing break

### Ambiguities — Pending Reconciliation with Approved Clarifications
1. **Empty search range edge case** (Section 7): starting candle is itself the first pullback candle; no eligible candle remains for tentative level. No behaviour approved. *(Flagged in all five documents.)*

### Candidate Test Scenarios
1. Basic upward cycle: 3 green candles → 2 red pullback → tentative high → close above → confirmed pair
2. Basic downward cycle: mirror of above with green pullback
3. Failed pullback: 2nd red candle does not close below 1st's wick → skip and continue searching
4. Flat candle in pullback run: interrupts colour sequence
5. Tied body edges: latest candle selected
6. Equality at comparison: does not satisfy (pullback, closing break)
7. Trend confirmation: 2 completed pairs with strictly higher highs and lows (upward)
8. "Trend not confirmed": equality in one comparison
9. Break candle is a pullback candle from old cycle → must occur after previous break
10. Edge case: starting candle = first pullback candle (empty range — expected: no level invented)

---

## 2. CHOCH — Change of Character

### Source Sections
- `Choch.pdf` — Sections 1–10 (complete document)
- Original authority: TopG.pdf pages 9–12

### Inputs and Configuration
- Active marking direction (from MSM)
- Latest confirmed support / resistance prices and candles (from MSM)
- Active tentative point 3 (from MSM current cycle)
- Completed candle data on H4 or D1

### Outputs
- CHOCH confirmed signal (bearish or bullish)
- Three zones with labels:
  - Bearish: SBR (confirmed low), QML/A+ (confirmed high), Double top (tentative point 3)
  - Bullish: QML/A+ (confirmed low), RBS (confirmed high), Double bottom (tentative point 3)
- Each zone: price range (body edge to wick tip) or single price line
- New marking direction and reference candle for restart

### State Transitions and Dependencies
1. **Monitoring**: reading MSM state; point 3 not yet identified → no qualifying close counted
2. **Point 3 active**: tentative level identified by current marking cycle
3. **First qualifying close**: one candle closes strictly beyond support/resistance in reversal direction
4. **Confirmed CHOCH**: immediately next candle also closes strictly beyond → zones created, old cycle ended
5. **Failed pair**: next candle does not close on required side → reset to monitoring for new consecutive pair
6. **Restart**: point 3's candle becomes new reference; marking begins in new direction

### Explicit Rules
- Bearish CHOCH: 2 consecutive candles close strictly below last support (upward structure)
- Bullish CHOCH: 2 consecutive candles close strictly above last resistance (downward structure)
- Single close insufficient; nonconsecutive closes cannot combine
- This is a closing-price rule, not a pullback-colour rule
- Point 3 must exist before first qualifying close
- Point 3 = active tentative level from current MSM cycle only
- If cycle completes (tentative becomes confirmed), point 3 is gone; need new pullback
- Zone construction: body edge to wick tip; zero-width → single price line
- Restart: first new-direction pullback must occur after CHOCH confirmation candle

### Ambiguities — Pending Reconciliation with Approved Clarifications
1. Inherited MSM empty-search-range edge case (Section 9)
2. No explicit rule for what happens if point 3 is confirmed and immediately a new pullback creates a new point 3 in the same candle sequence as a potential CHOCH close

### Candidate Test Scenarios
1. Basic bearish CHOCH: upward structure, point 3 exists, 2 consecutive closes below support → confirmed
2. Basic bullish CHOCH: downward structure, mirror scenario
3. Failed pair: first close below support, second close at or above → no CHOCH
4. No point 3: closes below support but no active tentative level → not counted
5. Point 3 completes (becomes confirmed) before CHOCH → need new pullback
6. Zone construction with zero-width wick (no wick on relevant side)
7. Restart: verify first new-direction pullback is after confirmation candle
8. Equal close (at support level exactly) → does not qualify

---

## 3. ISS — Internal Structure Shift

### Source Sections
- `ISS.pdf` — Sections 1–14 (complete document)
- Original authority: TopG.pdf pages 15–16

### Inputs and Configuration
- Main level 2 (confirmed low/high from MSM) — price and candle
- Main level 3 (active tentative high/low from MSM) — price and candle
- Fixed boundary: inclusive interval [level 2, level 3] body-edge prices
- Candle data on H1 timeframe (source timeframe for ISS)

### Outputs
- ISS confirmed signal
- Two zones with labels:
  - Bearish main: ISS level 3 = Internal CH2 (RBS), ISS level 4/A+ = Internal CL2 (buying A+)
  - Bullish main: ISS level 3 = Internal CL2 (SBR), ISS level 4/A+ = Internal CH2 (selling A+)
- Each zone: body edge to wick tip or single price line
- ISS state: eligible search / confirmed / rejected / tracking-only

### State Transitions and Dependencies
1. **Idle**: no active main level 3
2. **Eligible search**: main level 3 identified → internal marking begins in opposite direction within fixed boundaries
3. **Building internal structure**: accumulating 5 internal points (CH1, CL1, CH2, CL2, tentative)
4. **Confirmed ISS**: 5th point identified, all 5 prices within boundary, completion close within boundary → zones created
5. **Out-of-bounds marked level**: any internal level outside boundary → reject, remove candidate, stop internal marking
6. **Outside-range completion close**: levels valid but completion close outside boundary → no ISS, retain tracking only
7. **Main continuation**: main break confirms level 3 before ISS completes → cancel ISS candidate
8. **Main CHOCH**: cancel any unfinished ISS, apply CHOCH transition
9. **New main level 3**: fresh ISS search with new boundaries

### Explicit Rules
- Five internal points = 2 confirmed highs + 2 confirmed lows + 1 tentative (not 5 arbitrary legs)
- Internal marking uses MSM rules (pullbacks, body edges, ties, etc.)
- Fixed boundary prices captured at search start; not updated
- Equality at boundary IS valid (exception to strict comparisons)
- Check 5 marked prices, not every intervening candle
- Wick excursions outside range do not invalidate
- Confirm at 5th-point pullback close, not at continuation break
- One ISS per main level 3
- Out-of-bounds: reject permanently for that level 3, remove markings
- Outside-range completion close: reject permanently, but retain internal marking for tracking
- ISS does not change main direction
- No same-candle ISS/main-CHOCH priority rule

### Ambiguities — Pending Reconciliation with Approved Clarifications
1. Inherited MSM empty-search-range edge case
2. No explicit rule for the internal marking starting candle being the first internal pullback candle (inherits the same ambiguity)

### Candidate Test Scenarios
1. Complete 5-point ISS within boundaries → confirmed, zones created
2. 4th internal point falls outside boundary → rejected, no zones
3. 5 valid points but completion close outside boundary → no ISS, tracking only
4. Main continuation break before ISS completes → ISS cancelled
5. Main CHOCH during active ISS search → ISS cancelled
6. Price at boundary exactly (equality) → valid
7. New main level 3 while waiting → fresh ISS search
8. Wick extends outside boundary but body-edge level is inside → valid
9. Second ISS attempt under same main level 3 after rejection → not allowed

---

## 4. TJL — Trend Joining Level

### Source Sections
- `TJL.pdf` — Sections 1–9 (complete document)
- Original authority: TopG.pdf pages 17–18

### Inputs and Configuration
- Confirmed high and confirmed low from MSM (on H4 and H1 separately)
- Main structure direction
- Source candles for each confirmed point

### Outputs
- TJL1 label and zone (confirmed high in bullish / confirmed low in bearish)
- TJL2 / A+ label and zone (confirmed low/LSM in bullish / confirmed high/LRM in bearish)
- Zone price ranges or single price lines
- Current active TJL set

### State Transitions and Dependencies
- TJL is a labeling layer on top of MSM; no independent state machine
- When MSM establishes/updates a confirmed point → TJL label and zone auto-assigned
- On main CHOCH → old TJL trading roles deactivated; new direction TJLs assigned as new confirmed points form

### Explicit Rules
- TJL uses only confirmed points, never tentative
- Zone construction: same body-edge-to-wick rules as other modules
- Only latest TJL2 / A+ is trading-eligible
- No volatility classification (explicitly excluded by user)
- TJL1 marked but not trading-eligible under this module
- No independent TJL confirmation event; follows MSM timing

### Ambiguities — Pending Reconciliation with Approved Clarifications
1. No historical-retention/deletion policy for older TJL zones on the display
2. Inherited MSM empty-search-range edge case

### Candidate Test Scenarios
1. Bullish structure: confirmed high → TJL1, confirmed low → TJL2/A+ (LSM)
2. Bearish structure: mirror labels
3. New confirmed pair updates TJL labels automatically
4. Main CHOCH → old TJL roles deactivated
5. Zero-width zone (no wick) → single price line

---

## 5. MTF — Multi-Timeframe Entry Confirmation

### Source Sections
- `MTF-Analysis.pdf` — Sections 1–13 (complete document)
- Baseline: Entry_and_Confirmation_New_Rules.pdf, Version 1, 24 October 2026
- User approvals through 26 October 2026, 12:58 AM IST

### Inputs and Configuration
- TJL levels on D1, H4, H1 (independently marked)
- Candle data on D1, H4, H1, M5, M1
- CHOCH and ISS detection state on confirmation timeframes (H1, M5, M1)
- Monday-to-Monday marking cycle for TJL set retention

### Outputs
- Active TJL level activations (per source timeframe)
- Confirmation signals (fresh CHOCH or ISS on mapped confirmation timeframe)
- Entry signal at confirmation close
- Used-level tracking per source timeframe and level
- Cancellation events

### State Transitions and Dependencies
1. **TJL levels marked**: D1, H4, H1 independently
2. **Tap**: wick touch of unused eligible TJL zone → activation starts confirmation search
3. **Confirmation search active**: monitoring mapped lower timeframe for fresh CHOCH or ISS
4. **Entry confirmed**: fresh directional CHOCH or ISS on mapped timeframe → entry at confirmation close
5. **Level used**: one trade per level; used level cannot reactivate
6. **Cancelled**: replaced TJL set, main CHOCH on source, or another entry wins
7. **Reactivation**: unused cancelled level may reactivate with fresh tap (price must leave and re-enter zone)

### Explicit Rules
- Confirmation mapping: D1 → H1, H4 → M5, H1 → M1
- Accepted patterns: Normal CHOCH or ISS only
- Buy: fresh bullish CHOCH/ISS; Sell: fresh bearish CHOCH/ISS
- Existing aligned trend is NOT sufficient; must be fresh transition
- Pattern may start before tap but must confirm on tap candle or after
- Tap candle can also confirm → enter at that close
- Do not wait for retest of CHOCH/ISS zones
- Confirming candle need not close inside TJL zone
- Competing activations: first valid confirmation timestamp wins
- Timestamp tie: prefer lower confirmation TF (M1 > M5 > H1)
- Same-source TJL1 vs TJL2 tie: TJL2/A+ wins
- One trade per level; touch ≠ usage; entry = usage
- Cancellation: replacement TJL on same source TF; source main CHOCH; entry from any level
- Reactivation requires price to leave zone and re-touch; remaining inside doesn't count
- Monday-to-Monday retention: Monday alone doesn't delete, cancel, or reset
- Both TJL1 and TJL2 use same activation rule; no TJL1 breakout-retest requirement

### Ambiguities — Pending Reconciliation with Approved Clarifications
1. Inherited MSM empty-search-range edge case
2. Broker order type, fill handling, and live execution mechanics not defined
3. No zone expiry period defined
4. No structural stop loss, target formula, or risk percentage defined (explicitly out of scope)
5. TJL historical display/archival policy not defined

### Candidate Test Scenarios
1. D1 TJL2 tapped → monitor H1 for fresh bullish CHOCH → entry at confirmation close
2. H4 TJL1 tapped → monitor M5 for fresh bearish ISS → entry at confirmation close
3. Tap candle itself confirms CHOCH → immediate entry
4. Pattern begins before tap, confirms after → valid
5. Confirmation completes before tap → not reusable
6. Two activations: H4 confirms at timestamp T, D1 confirms at timestamp T+1 → H4 wins
7. Same timestamp tie: M1 wins over M5
8. TJL1 and TJL2 same source confirm simultaneously → TJL2 wins
9. Entry on H4 → all other activations (D1, H1) cancelled, not marked used
10. Used level re-tapped → no activation
11. Cancelled unused level: price leaves zone, re-taps → fresh activation with fresh confirmation requirement
12. Monday arrives, no new 3-point set → levels retained, used status retained
13. Source main CHOCH → immediate cancellation of activation
14. Replacement TJL on same TF → cancel old activation

---

## Cross-Module Dependency Graph

```
MSM (Market Structure Marking)
 ├─→ CHOCH (reads confirmed levels + active tentative from MSM)
 ├─→ ISS (reads main level 2 and 3 from MSM; uses MSM rules internally)
 ├─→ TJL (labels confirmed MSM points)
 │    └─→ MTF Entry Confirmation (monitors TJL zones; uses CHOCH and ISS on lower TFs)
 └─→ All modules inherit MSM's candle measurement and comparison rules
```

## Shared Unresolved Issue

> [!WARNING]
> **Empty search range edge case**: All five documents flag the same unresolved MSM boundary case where the user-selected starting candle is itself the first pullback candle, leaving no eligible range for the tentative level. No behaviour has been approved. This is **pending reconciliation with approved clarifications**.
