# Fixture Specification: `tjl_08_idempotent_reobservation_same_fingerprint`

**Category**: end_to_end_msm_derived, source_settled  
**Scope**: Set Evaluation Idempotence  

## 1. Description & Strategy Context
Re-evaluating the engine across consecutive bars (Bars 10, 11, 12 in Bearish structure) where price fluctuates within structure without breaking continuation or identifying a new P3.

## 2. Acceptance Assertions
- Fingerprint at Bar 10 == Fingerprint at Bar 11 == Fingerprint at Bar 12.
- `is_idempotent == True`.
- `replacements_count == 0`.
- `cancellation_intents_count == 0`.
