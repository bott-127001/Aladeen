# Fixture Specification: `tjl_06_pullback_t2_replacement_and_cancellation_intent`

**Category**: end_to_end_msm_derived, source_settled  
**Lifecycle State**: $t_2$ (Next Pullback Completion)  
**Source Engine ID**: `ENGINE_GBPUSD_H1`  

## 1. Description & Strategy Context
Follows state $t_1$: subsequent candles (Bars 15–16) form a valid 2-candle pullback. At Bar 16 close, active Tentative Low P3_2 (Bar 14, price 1.1320) is identified.

## 2. Acceptance Assertions (OPEN-02 $t_2$ Rule)
- A new fingerprint is formed: `("ENGINE_GBPUSD_H1", "DOWNWARD", 13, 7, 14)`.
- **Set Replacement Occurs**: Set 2 replaces Set 1 as the current eligible set.
- **Outgoing Cancellation Intent**: Emits `outgoing_cancellation_intent = True` for Set 1.
- Pending activations on Set 1 are invalidated. The replacement set requires its own fresh tap.
- Member availability for Set 2 is Bar 16 close time (`2026-10-01T17:00:00Z`).
