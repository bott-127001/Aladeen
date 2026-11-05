# Fixture Specification: `tjl_09_source_choch_eligibility_invalidation_and_gap`

**Category**: end_to_end_msm_derived, source_settled  
**Scope**: Source Main CHOCH Invalidation & Transition Gap  

## 1. Description & Strategy Context
At Bar 11 of `choch_bearish_basic_end_to_end`, two consecutive closes below last support confirm Main Bearish CHOCH on the source timeframe.

## 2. Acceptance Assertions
- `main_choch_confirmed == True` (`BEARISH_CHOCH`).
- Old-direction (Bullish) trading eligibility is immediately invalidated (`outgoing_cancellation_intent == True`).
- **Post-CHOCH Transition Gap**: At Bar 11, `current_set == None`. No set is eligible in either direction until new structure establishes confirmed pairs + active P3.
- Historical labels, zones, and stable level identities remain preserved in history.
