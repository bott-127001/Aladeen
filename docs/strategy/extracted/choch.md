# CHOCH — Approved Rules — Transcription

> **Source**: `docs/strategy/Choch.pdf`
> **Version**: 2 | Confirmation conditions restored | 13 October 2026

---

## 1. Scope and Source of Rules

This module defines bearish and bullish CHOCH on H4 and daily charts, using TopG pages 9–12 together with the refinements approved in discussion. It operates alongside the separate Market Structure Marking specification. It does not define entries, execution, or profitability.

This revision adds the previously omitted consecutive-close conditions and removes the obsolete statements that those conditions were unavailable. Existing approved point-3, zone, and restart rules are preserved.

## 2. Levels and Candle Measurements

- **Last support** is the latest confirmed low in upward marking. **Last resistance** is the latest confirmed high in downward marking. Tentative levels do not replace these confirmed levels.
- Use the body-edge prices established by the marking module for the support/resistance closing comparisons; zone wick boundaries do not replace those comparison prices.
- Evaluate completed candles only. A wick crossing a level does not qualify without the required close.
- Below means strictly below; above means strictly above. A close equal to the level does not qualify.

## 3. Exact CHOCH Confirmation Conditions

- **Bearish CHOCH**: while marking upward structure, two consecutive completed candles must both close strictly below last support. Confirm CHOCH only when the second candle closes below that level. The second candle's colour does not matter.
- **Bullish CHOCH**: while marking downward structure, two consecutive completed candles must both close strictly above last resistance. Confirm CHOCH only when the second candle closes above that level. The second candle's colour does not matter.
- A single qualifying close is not confirmed CHOCH. If the immediately following candle does not close on the required side, that pair fails; do not combine the first close with a later nonconsecutive close. Search for a new eligible consecutive pair. This includes a next candle that closes at the level or back on the original side.
- The confirmation rule is a closing-price rule, not a two-red-candle or two-green-candle pullback rule. Candle colour cannot substitute for the required closes.

## 4. Point 3 Eligibility and Counting

- Point 3 must already be identified when the first qualifying CHOCH candle closes. Earlier closes do not count toward confirmation.
- Both consecutive closes used for confirmation must belong to an eligible pair under this timing rule.
- Use only the active tentative level maintained by the current marking cycle as point 3: the active tentative high in upward structure, or the active tentative low in downward structure. Do not replace it with a later unconfirmed higher high or lower low merely because price reaches that extreme.
- Another pullback does not start an independent marking cycle while the existing cycle waits for its closing break. If that cycle completes, its tentative level becomes confirmed and is no longer an active point 3. The next valid pullback must identify a new point 3.

## 5. Three Zones and Their Directional Roles

On confirmed CHOCH, use the original candles of the confirmed low, confirmed high, and active tentative point 3 to create the three zones.

| CHOCH   | Confirmed low | Confirmed high | Tentative point 3 |
|---------|---------------|----------------|--------------------|
| Bearish | SBR           | QML / A+       | Double top         |
| Bullish | QML / A+      | RBS            | Double bottom      |

- **SBR**: support becomes resistance.
- **RBS**: resistance becomes support.
- Retain the QML / A+ and double-top/bottom labels as agreed.

## 6. Zone Boundaries and Zero-Width Zones

- **Upper body edge** is max(open, close); **lower body edge** is min(open, close).
- A high-side zone extends from the original candle's upper body edge to its top wick tip.
- A low-side zone extends from its bottom wick tip to its lower body edge.
- If the original candle has no wick on the relevant side, retain a single price line with the assigned label. Do not widen it artificially or substitute another candle. This applies equally to high-side and low-side zones.

## 7. End the Old Cycle and Restart

- At the second qualifying candle's close, end the old direction's unfinished marking cycle. It no longer waits for its original continuation break.
- Preserve earlier confirmed levels in history and assign the three zone roles above.
- Use point 3's original candle as the new reference candle and begin marking in the new direction: bearish after bearish CHOCH, bullish after bullish CHOCH.
- Both candles of the first new-direction pullback must occur after the CHOCH confirmation candle; that candle cannot be reused as a pullback candle.

## 8. Processing Sequence

1. Read the active direction, latest confirmed support/resistance, and active tentative point 3 from the marking module.
2. Count no qualifying close before point 3 is identified.
3. Require two adjacent completed candles to close strictly beyond the applicable confirmed level in the reversal direction.
4. Confirm CHOCH at the second qualifying close; a failed pair does not confirm a direction change.
5. End the old unfinished cycle and preserve confirmed history.
6. Create and label the three original-candle zones, retaining zero-width zones as price lines.
7. Set point 3's candle as the new reference and begin opposite-direction marking.
8. Accept the first new-direction pullback only when both its candles occur after confirmation.

## 9. Integration Boundary and Remaining Issue

- Valid pullbacks, continuation breaks, search windows, body-edge selection, and ties are defined in Market Structure Marking, not redefined here.
- The missing CHOCH confirmation conditions and consecutiveness are now explicitly documented.
- One separate marking edge case remains unresolved in the marking document: the selected starting candle is itself the first candle of the first valid pullback, leaving no eligible tentative-level search range. The proposal to skip that pair has not been approved in the supplied conversation. This revision does not silently approve it or claim the combined modules are implementation-complete.

## 10. Source Record

Sources: TopG.pdf pages 9–12 (CHOCH conditions and zone roles); Market Structure Marking, version 2 (marking definitions and integration boundary); original CHOCH.pdf and user approvals through 13 October 2026 (active tentative point 3, timing, zones, zero-width treatment, and restart).
