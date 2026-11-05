# MTF Analysis and Entry Confirmation — Transcription

> **Source**: `docs/strategy/MTF-Analysis.pdf`
> **Version**: 1 — Consolidated rule record | 26 October 2026 | IST
> Combines Entry_and_Confirmation_New_Rules.pdf (24 October 2026) with all subsequent user-approved decisions in the discussion through 12:58 AM IST on 26 October 2026.

---

## 1. Scope, Authority and Status

This is the fresh multi-timeframe analysis and entry specification. The 24 October baseline is retained except where the subsequent discussion explicitly defines or changes a rule. Its statement that entry confirmation was undefined is superseded by the approved rules below. No other historical execution policy or filter is imported automatically.

The original D1/H4/H1 trend-alignment and timeframe-selection observations are excluded: the user identified them as disproven. No agreement between source timeframes is required to select a trade.

This document records conceptual decisions. It is not evidence of implementation, testing, executable order integration or profitability. Stop loss, targets, position sizing and post-entry trade management remain the user's responsibility.

## 2. Analysis Versus Trade Finding

- TJL is the only source of marked trade-finding levels. Market structure supplies the structural points.
- Main CHOCH and ISS serve analysis; on the assigned lower timeframe, normal CHOCH and ISS also serve as entry confirmation after a TJL activation.
- Their zones are not independent trade-finding setups in this specification.

## 3. Source Timeframes, Structure and Direction

Mark TJL on D1, H4 and H1 independently. On each, track the latest three structural points: confirmed high, confirmed low, and active tentative high or low according to structure. Use the existing trend-identification method; it is not redefined here. Mark only the two confirmed points as TJL levels, not the tentative point.

| Source structure | TJL1           | TJL2 / A+     | Trade side for both |
|-----------------|----------------|----------------|---------------------|
| Bullish         | Confirmed high | Confirmed low  | Buy                 |
| Bearish         | Confirmed low  | Confirmed high | Sell                |

- TJL1 follows the source structure trend, not an opposite trade merely because its source point is a high or low.
- TJL1 and TJL2 use the same activation rule. No additional TJL1 breakout-and-retest requirement is imposed.

## 4. Marked-Set Updates and Weekly Retention

- Use a Monday-to-Monday marking cycle. Replace the marked set when a new latest three-point set forms. If the next Monday arrives without a new three-point set, retain the existing levels.
- Monday alone does not delete a level, cancel activation, replace a set or reset usage. A retained used level remains used.
- Retain the existing approved TJL zone-construction rules: original source candle; high-side zone from upper body edge to top wick, low-side zone from bottom wick to lower body edge. A missing relevant wick leaves a labeled single price line, not an artificially widened zone. These are inherited marking rules, not a new entry filter.

## 5. Tap and Activation

- Any wick touch of a TJL zone is sufficient. Touching a zone boundary or entering the zone counts; a close inside is not required. Only an unused, currently eligible level can activate.
- Price decides which source timeframe/level is monitored by tapping it.
- The first tap starts its confirmation search. Further taps while that activation remains pending do not restart or reset the search. A tap is not itself an entry signal.

## 6. Confirmation Mapping and Direction

| Tapped TJL timeframe | Confirmation timeframe | Accepted patterns     |
|----------------------|------------------------|-----------------------|
| D1                   | H1                     | Normal CHOCH or ISS   |
| H4                   | M5                     | Normal CHOCH or ISS   |
| H1                   | M1                     | Normal CHOCH or ISS   |

- Apply the existing approved normal CHOCH and ISS detection rules unchanged on all assigned confirmation timeframes: H1, M5 and M1. This explicitly extends confirmation use beyond the previous timeframe scopes; it does not change their detection logic.
- For buys, require fresh bullish normal CHOCH or bullish ISS. For sells, require fresh bearish normal CHOCH or bearish ISS. An already-aligned trend is not sufficient.
- ISS confirmation means a newly confirmed directional ISS signal, not a requirement to also wait for main CHOCH.
- Detection dependencies remain Choch.pdf, ISS.pdf and Market Structure Marking.docx. Normal CHOCH retains its consecutive-close and eligible-point-3 conditions. ISS retains its five-point, fixed-boundary and completion-close conditions. This document changes their permitted confirmation timeframes, not those conditions.

## 7. Confirmation Timing and Entry

- A pattern may start forming before the first tap, but must confirm on the tap candle or afterward. A confirmation completed before activation cannot be reused. The entire pattern need not form after the tap.
- The tap candle may also confirm the pattern; enter at that candle's close if valid. Otherwise enter immediately at the later qualifying confirmation close. Do not wait for a retest of zones created by CHOCH or ISS.
- The confirming candle need not close inside the tapped source TJL zone. Confirmation remains eligible after price has moved away from the zone, provided activation has not been cancelled.
- Entry at the confirmation close is conceptual timing; broker order type, fill handling and live execution mechanics are not defined here.

## 8. Competing Activations and Tie-Breakers

- Monitor simultaneously active levels on their mapped timeframes. The first valid confirmation by closing timestamp wins, regardless of timeframe. The earlier proposal to always prioritize the lower timeframe was replaced by this rule.
- If valid confirmations share exactly the same closing timestamp, prefer the lower confirmation timeframe: M1 before M5 before H1.
- If TJL1 and TJL2 from the same source timeframe qualify simultaneously, choose TJL2 because it is A+.
- Take one selected entry, mark its source TJL level used, and cancel all other pending activations across D1, H4 and H1. Cancellation of those other activations does not itself mark their levels used.

## 9. Cancellation and Reactivation

| Event | Required action |
|-------|-----------------|
| Replacement TJL set on the same source timeframe | Cancel activation of the replaced level; the replacement needs its own tap. |
| New TJL on another source timeframe | Do not cancel solely because of that update. |
| Main CHOCH on the activated level's source timeframe | Immediately cancel old-direction activation, even before replacement TJLs form. |
| Entry from any selected active level | Cancel all other pending activations. |
| Further touch while activation is pending | Keep the original search running. |

- An unused level cancelled because another entry won may reactivate if still current and eligible. Price must leave its zone and touch it again. Remaining in the zone does not count. The new activation requires a fresh qualifying confirmation on its tap candle or afterward; an earlier confirmation is not reusable.
- Reactivation does not revive a replaced level or an old-direction TJL role invalidated by source main CHOCH. New levels do not inherit previous activations.

## 10. One Trade Per Level

- Each particular TJL level can supply at most one trade. Track used status separately for each source timeframe and each level.
- A touch is not usage; the selected entry is usage. Repeated taps, cancellations, reactivations and weekly carry-over do not reset a used level.
- **Example**: an H4 entry wins while D1 is also active. H4's traded level becomes used. D1 activation is cancelled but its level stays unused. If still eligible, D1 may reactivate after price leaves and retouches its zone. Trading a different level never restores the old used level.

## 11. User-Owned Risk and Management

Stop loss, targets, position sizing and post-entry trade management are outside this specification and remain with the user. No structural stop reference, buffer, target formula, risk percentage or management policy is inferred.

## 12. Complete Discussion Question-and-Answer Record

| # | Question | Answer |
|---|----------|--------|
| 1 | Use the original multi-timeframe alignment/priority table? | No. Exclude it as a disproven observation; taps select the relevant levels. |
| 2 | What activates a level? | Price taps a TJL level; that source timeframe/level becomes active for confirmation. |
| 3 | Which confirmation timeframes? | D1 → H1; H4 → M5; H1 → M1. |
| 4 | Must confirmation agree with the intended trade side? | Yes. Bullish for buys; bearish for sells. |
| 5 | May confirmation occur after price leaves the source zone? | Yes. Its close need not be inside the zone. |
| 6 | Enter at confirmation or wait for a retest? | Enter immediately at the CHOCH/ISS confirmation close. |
| 7 | Which patterns qualify? | Normal CHOCH or ISS / five-wave CHOCH. |
| 8 | Who defines stop loss? | The user; exclude it from this specification. |
| 9 | Who handles targets, sizing and trade management? | The user; all are outside this specification. |
| 10 | What new-level update cancels pending activation? | Replacement TJL on the same source timeframe only; another timeframe's update does not. |
| 11 | Is a wick touch sufficient? | Yes. No close within the zone is required. |
| 12 | Can the tap candle also confirm entry? | Yes. Enter at that close if it confirms a valid directional pattern. |
| 13 | Do repeated taps restart the search? | No. Keep it running from the first tap. |
| 14 | May the pattern begin before the tap? | Yes, if it confirms on the tap candle or afterward. |
| 15 | Which active timeframe wins? | The first valid confirmation, regardless of timeframe. This supersedes blanket lower-timeframe priority. |
| 16 | What happens to other pending activations after entry? | Cancel them all. |
| 17 | May unused cancelled levels reactivate? | Yes, but each particular level can still provide only one trade total. |
| 18 | How are identical confirmation timestamps resolved? | Choose the lower confirmation timeframe: M1, then M5, then H1. |
| 19 | Is an existing aligned trend sufficient? | No. Require a fresh transition for every confirmation. |
| 20 | Which direction is traded from TJL1? | Follow the source structure trend: bullish buys, bearish sells. |
| 21 | Does TJL1 need a separate breakout and retest? | No. Use the same activation rule as TJL2. |
| 22 | If TJL1 and TJL2 on one source timeframe qualify simultaneously? | Choose TJL2 / A+ and mark it used; cancel TJL1 activation without marking it used. |
| 23 | Apply existing CHOCH/ISS rules on H1, M5 and M1? | Yes, unchanged detection logic on those confirmation timeframes. |
| 24 | Cancel if source main CHOCH occurs before entry? | Yes, immediately, even without replacement TJLs. |
| 25 | What constitutes a fresh tap after cancellation? | Price leaves the zone and touches it again; remaining inside does not qualify. |

## 13. Source Record and Remaining Boundary

- **Baseline**: Entry_and_Confirmation_New_Rules.pdf, Version 1, 24 October 2026.
- **Added authority**: user approvals in this conversation on 26 October 2026 through 12:58 AM IST.
- **Detection/marking dependencies**: Market Structure Marking.docx, Choch.pdf, ISS.pdf and TJL.pdf, subject to the explicit overrides in this document.
- The baseline's formerly undefined entry patterns, timeframe mapping, tap behaviour, priorities and conceptual entry timing are now defined here. The original notes' rejected alignment policy, old TJL2-only eligibility restriction and volatility selection are not imported.
- The separate initial starting-candle empty-search-range issue in Market Structure Marking remains unresolved. This entry specification does not silently resolve it.
- No new expiry period, extra confirmation filter, automatic order-routing policy or performance claim has been added.
