# Fixture Specification: `tjl_05_continuation_t1_labels_without_replacement`

**Category**: end_to_end_msm_derived, source_settled  
**Lifecycle State**: $t_1$ (Continuation Break)  

## 1. Description & Strategy Context
Evaluates state $t_1$ across a continuation break in Bearish structure (at Bar 14 of `iss_09`).
- Price closes below 1.1400, breaking continuation.
- MSM confirms Pair 2: CH2 at Bar 13 (1.1680) and CL2 at Bar 7 (1.1400).
- P3 is cleared because continuation broke the tentative level; **active P3 is None**.

## 2. Acceptance Assertions (OPEN-02 $t_1$ Rule)
- Newly confirmed points receive next labels (CH2 becomes next TJL2, CL2 becomes next TJL1).
- **Current Set is NOT Replaced**: Set 1 (from Bar 9) remains current and eligible!
- `is_current_set_replaced == False`.
- `outgoing_cancellation_intent == False`.
- **Core Strategy Rule**: Continuation labels at $t_1$ do NOT replace the current set until the next P3 identification at $t_2$.
