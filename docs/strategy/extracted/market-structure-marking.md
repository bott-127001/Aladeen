# Market Structure Marking — Transcription

> **Source**: `docs/strategy/Market Structure Marking.docx`
> **Version**: 2 — Approved marking rules | 13 October 2026
> **Scope**: Important-level marking from TopG.pdf pages 1–8 and the decisions approved in discussion. CHOCH, entries and trade execution are outside this module. This document specifies marking behaviour, not profitability.

---

## 1. Starting Inputs

- The user selects the starting candle and the starting direction: upward or downward. The software does not choose these automatically.
- The notes specify four-hour and daily charts for this module. Apply the rules separately to the selected chart.
- Use completed candles only. A developing candle cannot establish a pullback, closing break or confirmed level.

## 2. Candle Measurements and Equal Values

- **Upper body edge**: whichever is higher, opening price or closing price.
- **Lower body edge**: whichever is lower, opening price or closing price.
- All marked tentative and confirmed highs/lows use body edges, not wick tips.
- Only the two-candle pullback comparison uses the first candle's wick extreme. The second candle must CLOSE beyond it; its wick crossing alone is insufficient.
- **Red**: closing price below opening price. **Green**: closing price above opening price. **Equal opening and closing prices**: neither red nor green.
- A flat candle interrupts a required-colour pullback run, but remains eligible for body-edge searches and closing breaks.
- When eligible candles share the same extreme body edge, select the latest candle. This applies to tentative levels and opposite levels confirmed by breaks.
- Above and below mean strictly above and strictly below. Equality never satisfies a pullback or closing-break comparison.

## 3. Upward Marking Algorithm

1. Set the search-start candle to the user's starting candle. Begin looking for a valid pullback from that starting candle onward.
2. Find two consecutive red candles whose second candle closes strictly below the first candle's bottom wick tip.
3. If a pair fails, move forward one candle: test candles 2 and 3 if both are red, then 3 and 4, and so on. A non-red candle interrupts the run.
4. Once a valid pair finishes, find the highest upper body edge from the search-start candle through the candle immediately before the first red candle. Include the search-start candle; exclude both pullback candles. Choose the latest candle if tied. This is the **tentative high**.
5. Wait for a later completed candle to close strictly above the tentative high. Neither pullback candle can serve as this closing break. The break candle's colour does not matter. Do not start another independent cycle while waiting.
6. On that closing break, the tentative high becomes **confirmed**. Find the lowest lower body edge from the candle containing that high through the closing-break candle. Include both endpoints and choose the latest candle if tied. That is the **confirmed low**.
7. The newly confirmed low becomes **last support**. Preserve earlier confirmed levels in the history.
8. Set the next search-start candle to the candle containing that newly confirmed low. The next high search includes it. Both candles of the next valid pullback must occur after the previous closing-break candle; that break candle cannot be reused as a pullback candle.
9. Repeat steps 2–8. The high search can look back to the new search-start candle, but the search for a new pullback pair begins only after the previous break.

## 4. Downward Marking Algorithm

1. Set the search-start candle to the user's starting candle. Begin looking for a valid pullback from that starting candle onward.
2. Find two consecutive green candles whose second candle closes strictly above the first candle's top wick tip.
3. If a pair fails, move forward one candle: test candles 2 and 3 if both are green, then 3 and 4, and so on. A non-green candle interrupts the run.
4. Once a valid pair finishes, find the lowest lower body edge from the search-start candle through the candle immediately before the first green candle. Include the search-start candle; exclude both pullback candles. Choose the latest candle if tied. This is the **tentative low**.
5. Wait for a later completed candle to close strictly below the tentative low. Neither pullback candle can serve as this closing break. The break candle's colour does not matter. Do not start another independent cycle while waiting.
6. On that closing break, the tentative low becomes **confirmed**. Find the highest upper body edge from the candle containing that low through the closing-break candle. Include both endpoints and choose the latest candle if tied. That is the **confirmed high**.
7. The newly confirmed high becomes **last resistance**. Preserve earlier confirmed levels in the history.
8. Set the next search-start candle to the candle containing that newly confirmed high. The next low search includes it. Both candles of the next valid pullback must occur after the previous closing-break candle; that break candle cannot be reused as a pullback candle.
9. Repeat steps 2–8. The low search can look back to the new search-start candle, but the search for a new pullback pair begins only after the previous break.

## 5. Labels and Trend Checks

- **Tentative high**: the upward level identified by a valid red pullback, waiting for a later close above it.
- **Tentative low**: the downward level identified by a valid green pullback, waiting for a later close below it.
- A closing break confirms the tentative level and its opposite level at the same time. Together they form one completed pair.
- **Last support**: the latest confirmed low in upward marking. **Last resistance**: the latest confirmed high in downward marking. A tentative point never replaces either.
- Before two completed pairs exist, display "Marking upward structure" or "Marking downward structure," according to the selected direction.
- Once at least two completed pairs exist, compare the latest two pairs after each completion:
  - **Upward trend**: newer high strictly higher AND newer low strictly higher.
  - **Downward trend**: newer high strictly lower AND newer low strictly lower.
- If either comparison fails, including equality, display "Trend not confirmed." Do not automatically switch direction.

## 6. Scope Boundary: CHOCH

- Handling a break of opposite support or resistance belongs to the separate CHOCH module. No pause-and-flag, automatic reversal, or CHOCH confirmation rule has been approved here.
- This document is complete for the approved marking sequence, but it is not a standalone rulebook for trading through direction changes. That integration must use the later CHOCH specification.

## 7. Consistency Review: One Initial-Range Edge Case

- The approved rules leave one unusual boundary case: the user selects a starting candle that itself becomes the first candle of the first valid pullback. Because the starting candle must be included but both pullback candles must be excluded, no eligible candle remains for the first tentative level.
- No behaviour for this empty range has been approved. The software must not invent a level or silently move the reference point. A proposed resolution is to require at least one eligible candle before accepting the first pullback; whether to skip that pair or require a different starting point still needs user approval.
- All other previously listed discussion decisions have been settled. This edge case is kept visible rather than labelled as approved.

## 8. Source and Approvals

- **Source**: TopG.pdf pages 1–8; Market Structure Marking version 1; user approvals in the discussion through 13 October 2026, 5:28 PM IST.
- The bearish trend comparison and bearish sequence have been corrected according to the user's approval: green pullback identifies low; later close below confirms high; falling highs and falling lows establish downward trend.
- Manual starting-point and direction selection are design rules, not temporary arrangements. Both pullback candles are excluded from tentative-level searches in both directions. Both endpoint candles are included in opposite-level searches.
- No implementation or trading execution has been performed.
