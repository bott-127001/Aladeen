# TJL — Trend Joining Level — Transcription

> **Source**: `docs/strategy/TJL.pdf`
> **Version**: 1 — Final marking rules | 14 October 2026, 4:58 PM IST

---

## 1. Scope and Status

All questions raised for the TJL marking module have been answered. This document consolidates the user-approved rules for H4 and H1, applied separately on each chart. TJL provides labels and zones for the existing confirmed market-structure points; it is not a separate structure-marking algorithm.

The source topic is TopG pages 17–18. The user-approved scope omits volatility classification, marks both TJL levels, and allows trading only from the latest TJL2 / A+ subject to a separate entry-confirmation specification. This document does not authorize entry on a zone touch or define trade execution.

## 2. Point-to-Label Mapping

| Main structure | TJL1           | TJL2 / A+                          |
|----------------|----------------|-------------------------------------|
| Bullish        | Confirmed high | Latest confirmed low / LSM          |
| Bearish        | Confirmed low  | Latest confirmed high / LRM         |

- **LSM** means last support in the market: latest confirmed low in bullish structure.
- **LRM** means last resistance in the market: latest confirmed high in bearish structure.
- Both TJL source points are confirmed; tentative highs/lows do not supply TJL zones.

## 3. Timing and Relationship to Main Marking

- Use exactly the existing approved confirmed-high/confirmed-low marking rules. Whenever those rules establish or update a confirmed point, its TJL name and zone follow automatically. There is no additional TJL pullback test, confirmation event, or independent search cycle.
- TJL labels do not change a point's confirmation status, source candle, marked price, or the main marking direction. Do not create or update a TJL zone merely because a tentative point is identified.
- Confirmed pairs follow the timing of the main marking module, not a newly invented TJL activation rule.

## 4. Zone Construction

- Use each confirmed point's original candle.
- Upper body edge = max(open, close); lower body edge = min(open, close).
- A high-point zone extends from the upper body edge to the top wick tip.
- A low-point zone extends from the bottom wick tip to the lower body edge.
- **Bullish TJL1** and **bearish TJL2** use high-side zones.
- **Bullish TJL2** and **bearish TJL1** use low-side zones.
- If the original candle has no wick on the relevant side, retain a labeled single price line. Do not widen it artificially or substitute another candle.

## 5. Latest Levels and Trading Eligibility

- Mark both TJL1 and TJL2 / A+. Consider the latest TJL levels established by current main marking; older TJL levels are not the current active set.
- Only the latest TJL2 / A+ is eligible for trading in this algo. TJL1 remains marked but is not eligible for trading under this module.
- Bullish TJL2 is the trend-joining buying zone; bearish TJL2 is the trend-joining selling zone.
- Eligibility is not an entry signal. Actual entry requires the confirmation rules to be defined later in the separate confirmation document.
- Do not classify normal versus volatile markets or switch trading eligibility to TJL1 based on volatility. This is an explicit user-approved subtraction from the source notes.

## 6. Main CHOCH Transition

- When main CHOCH confirms, the old direction's TJL zones stop being active TJL trading zones. Apply the approved CHOCH zone roles to the relevant points, using the separate CHOCH specification. Do not preserve an old TJL trading role simply because the same point is reused by CHOCH.
- Begin main marking in the new direction under the approved marking and CHOCH restart rules. Assign the new direction's TJL labels and zones as its confirmed highs/lows are established. There is no separate TJL confirmation event. Mark both levels; only the latest TJL2 / A+ is eligible for trading subject to later entry confirmation.

## 7. Implementation Sequence

1. Apply the approved main marking rules separately on H4 and H1.
2. When a confirmed high/low is established or updated, apply its direction-specific TJL label.
3. Build the zone from that confirmed point's original candle, including zero-width handling.
4. Maintain the latest TJL1 and TJL2 / A+ as the current set.
5. Expose only the latest TJL2 / A+ to the later entry-confirmation module; never enter solely because the zone exists.
6. On confirmed main CHOCH, deactivate old-direction TJL trading roles and apply CHOCH mapping and restart.
7. As confirmed points form in the new direction, automatically assign the new TJL labels and zones.

## 8. Dependencies and Limits

- Read with the approved Market Structure Marking and revised CHOCH specifications. Their rules govern confirmation, candle selection, ties, search windows, and direction changes.
- The separate initial starting-candle empty-search-range condition remains unresolved in the marking module; this document does not resolve it.
- Entry confirmation, stop loss, targets, position sizing, zone-touch execution, and additional expiry or invalidation policies are outside this marking file.
- No separate historical-retention/deletion policy was approved for older TJL drawings; this specification defines their loss of current active status, not how the interface archives or displays them.
- The TJL marking review is complete. This is an agreed rule document, not a statement that code has been implemented or tested.

## 9. Source and Approval Record

Basis: TopG.pdf pages 17–18; existing approved market-structure and body-to-wick zone rules; user decisions on 14 October 2026 through 4:57 PM IST. User decisions override source volatility-based selection. The user clarified that TJL is exactly the existing confirmed-high/low marking with new names and tradable zones, not a new confirmation process.
