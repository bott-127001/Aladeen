# Internal Structure Shift (ISS) — Transcription

> **Source**: `docs/strategy/ISS.pdf`
> **Version**: 1 — Final agreed rules | 13 October 2026, 11:16 PM IST

---

## 1. Scope and Authority

Separate ISS / 5-wave CHOCH module based on TopG pages 15–16 and the user-approved refinements in this conversation. H1 is the source timeframe. Engulfing retracement (page 13) and dual CHOCH (page 14) are excluded from the algo. This document defines detection, marking, zones, and search lifecycle; it does not define trade execution or profitability.

Explicit later corrections supersede earlier proposals. Main marking stays active throughout. ISS alone never changes the main marking direction. Main CHOCH is distinct from ISS and retains its own confirmation rules.

## 2. Main and Internal Numbering

- **Main level 2** is the confirmed low in bullish main structure or confirmed high in bearish main structure.
- **Main level 3** is the active tentative high in bullish main structure or active tentative low in bearish main structure. Its original candle is the internal search reference, not an ISS zone candle.
- **Five waves** means five internal marked points: two confirmed highs, two confirmed lows, and one tentative high/low. It does not mean five arbitrary price legs.
  - **Bearish main structure**: CH1 → CL1 → CH2 → CL2 → tentative high. Internal marking runs upward.
  - **Bullish main structure**: CL1 → CH1 → CL2 → CH2 → tentative low. Internal marking runs downward.

## 3. Begin an ISS Search

- After the valid two-candle main pullback identifies active main level 3, use that level's original candle as the internal search reference. Capture main level 2 and main level 3 prices and original candles. Fix those boundary prices for the entire candidate; later extremes do not move them.
- Both candles of the first internal pullback must occur after the second candle of that main pullback. Neither main pullback candle may be reused. The internal level search can still look back to the main level 3 reference candle.

## 4. Inherited Market-Structure Rules

Use the approved Market Structure Marking rules for internal pullbacks, tentative-level selection, confirmation, search windows, ties, and subsequent reference points. Use completed candles and body-edge marked levels. Strict above/below comparisons exclude equality; equality is allowed only for the ISS boundary test.

**Upward internal marking**: two consecutive red candles, with the second closing strictly below the first candle's bottom wick tip, identify a tentative high. Select the highest upper body edge from the reference through the candle before the pair, excluding both pullback candles; choose the latest candle if tied. A later close strictly above confirms the high and the lowest lower body edge from its candle through the break candle as the low, including both endpoints. The confirmed low becomes the next reference.

**Downward internal marking**: two consecutive green candles, with the second closing strictly above the first candle's top wick tip, identify a tentative low. Select the lowest lower body edge from the reference through the candle before the pair, excluding both pullback candles; choose the latest candle if tied. A later close strictly below confirms the low and the highest upper body edge from its candle through the break candle as the high, including both endpoints. The confirmed high becomes the next reference.

- Do not open an independent internal cycle while awaiting its continuation break.
- Both candles of the next internal pullback must occur after the previous break candle.
- Candle colour does not matter for a continuation closing break.
- Flat candles interrupt required-colour pullback pairs but remain eligible for body-edge searches and breaks.
- Upper body edge = max(open, close); lower body edge = min(open, close).

## 5. Fixed Price Boundary

- The allowed range is the inclusive interval between the captured main level 2 and main level 3 body-edge prices, regardless of which is higher.
- All five internal marked prices must lie inside that range. Equality at either boundary is valid.
- Check the five marked prices, not every intervening candle. Wick-only excursions outside the range do not invalidate ISS.
- The original zone wick can extend outside the range without invalidating an otherwise eligible body-edge level.

## 6. ISS Confirmation

- Confirm ISS at the close of the second candle of the valid internal two-candle pullback that identifies the fifth internal point: tentative high for bearish main structure, tentative low for bullish main structure.
- Do not wait for a continuation break confirming that fifth point.
- All five marked prices must satisfy the fixed boundary, and the completion candle itself must close inside that same inclusive range.
- No ISS is confirmed on an outside-range completion close.
- ISS is intended to signal before main CHOCH; a main support/resistance break is not an additional ISS prerequisite.

## 7. Zone Points, Roles, and Construction

- **ISS level 3** means the THIRD INTERNAL point.
- **ISS level 4 / A+** means the FOURTH INTERNAL point.
- Neither is supplied by main level 3 or by the fifth internal tentative point.

| Main direction | ISS level 3         | ISS level 4 / A+       |
|----------------|----------------------|-------------------------|
| Bearish        | Internal CH2: RBS    | Internal CL2: buying A+ |
| Bullish        | Internal CL2: SBR    | Internal CH2: selling A+|

- RBS means resistance becomes support; SBR means support becomes resistance. The A+ designation is retained as taught by the tutor; no additional justification or filter was approved.
- Create the two zones only on confirmed ISS. Use each internal point's original candle.
- High-side zones span upper body edge to top wick tip; low-side zones span bottom wick tip to lower body edge.
- With no relevant wick, retain a labeled single price line. Never widen artificially or substitute another candle.

## 8. Successful Signal and History

- Allow one confirmed ISS signal per main level 3. On confirmation, create the two zones and end that ISS search.
- Keep main marking active. A new valid main tentative level 3 permits a fresh search.
- Retain confirmed ISS zones and their original labels in history. Later confirmation of main level 3 or later main CHOCH does not retroactively cancel them.
- Retention does not establish ongoing trade eligibility; no zone expiry, trade invalidation, or entry-execution policy is defined here.

## 9. Out-of-Bounds Internal Marked Level

- If any internal marked level falls outside the fixed range, reject ISS eligibility for that main level 3.
- Remove that candidate's internal markings and stop its internal marking process. Create no ISS zones.
- Shift to monitoring main CHOCH, while keeping normal main marking active.
- Do not revive or restart the rejected candidate under the same main level 3. Previously confirmed ISS zones in history are not removed.
- A new valid main tentative level 3 permits a fresh ISS search even before main CHOCH confirms.

## 10. Outside-Range ISS Completion Close

- If all marked-level checks remain valid but the second candle of the fifth-point pullback closes outside the fixed range, do not confirm ISS or create its zones. That attempt permanently loses ISS eligibility under that main level 3.
- Unlike an out-of-bounds marked level, this case retains and continues internal level marking ONLY for tracking while awaiting main CHOCH. A later five-level sequence cannot revive ISS eligibility for that same main level 3.
- Keep normal main marking active. A new valid main tentative level 3 permits a fresh ISS search with new fixed boundaries.
- If a marked level itself is out of bounds, apply section 9 rather than using the completion-close exception to preserve that candidate's markings.

## 11. Main Continuation and Main CHOCH

- If a main continuation closing break confirms main tentative level 3 before ISS completes, cancel the unfinished ISS candidate without creating ISS zones. Normal main marking confirms its tentative level and opposite level and proceeds. Wait for a new valid main tentative level 3 to start a fresh ISS search.
- If the would-be ISS completion candle closes beyond main level 3 in the continuation direction, do not confirm ISS. Keep normal main marking active and apply its continuation rule. Monitor MAIN CHOCH, not internal CHOCH. A close beyond main level 3 alone is not a first main CHOCH close; it must independently meet the relevant main support/resistance condition.
- Main bearish CHOCH requires two consecutive completed closes strictly below main last support. Main bullish CHOCH requires two consecutive completed closes strictly above main last resistance. The second candle's colour does not matter. Apply the approved main CHOCH point-3 eligibility and timing conditions; waiting for another candle does not automatically confirm CHOCH.
- When main CHOCH confirms, cancel any unfinished ISS candidate or old tracking-only process. Apply the approved main CHOCH zone and restart rules. A fresh ISS search in the new direction requires a new valid main tentative level 3.
- No separate same-candle ISS/main-CHOCH priority rule is included. The user rejected that proposal and approved the completion-close boundary requirement to keep their confirmation conditions distinct.

## 12. Fresh-Search Rule After Waiting

- Whenever normal main marking identifies a new valid tentative level 3 while waiting for main CHOCH, start a fresh ISS search.
- Use the new level 3 original candle as reference, capture the current main level 2 and new level 3 as fixed boundaries, and require a fresh internal pullback pair.
- Do not revive the previous rejected candidate. Keep main marking and main CHOCH monitoring active.

## 13. Compact State Summary

| State | Description |
|-------|-------------|
| Eligible search | Build opposite-direction internal structure within fixed boundaries |
| Confirmed ISS | Create internal point-3 and point-4 zones; stop that search and retain history |
| Out-of-bounds marked point | Reject, remove candidate markings, stop internal marking, monitor main CHOCH |
| Outside-range completion close | No ISS; retain internal marking only for tracking; monitor main CHOCH |
| New main tentative level 3 | Open a fresh search with new captured boundaries |
| Main CHOCH | End old unfinished search/tracking and apply main CHOCH transition |
| Main continuation before completion | Cancel the candidate and continue main marking |

## 14. Dependencies and Sign-Off Scope

- All outstanding ISS review questions were answered by the user through 11:16 PM IST on 13 October 2026.
- This is the consolidated agreed ISS specification, not evidence of implementation or testing.
- Read with the approved Market Structure Marking and revised CHOCH specifications.
- The separate initial starting-candle empty-search-range condition in the marking module remains unresolved; this ISS document does not silently resolve it.
- **Source record**: TopG.pdf pages 15–16; approved marking and CHOCH definitions; user approvals and corrections in this ISS discussion. Later corrections concerning zone point 3, out-of-bounds handling, and fresh searches take precedence over earlier superseded proposals.
