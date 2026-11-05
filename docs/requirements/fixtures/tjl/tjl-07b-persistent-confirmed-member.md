# Fixture Specification: `tjl_07b_persistent_confirmed_member_across_replacement`

**Category**: synthetic_lifecycle_specification, source_settled  
**Scope**: Confirmed Member Survival & Replacement Invalidation (Case B & C)  

## 1. Description & Strategy Context
Demonstrates Case B & Case C:
- Set 1 has TJL members: TJL1 = `CH_1` (Bar 4), TJL2 = `CL_1` (Bar 7), and Tentative High `P3_1` (Bar 9).
- Later continuation break confirms `CH_2` (Bar 12) while `CL_1` (Bar 7) remains the un-broken swing low of the structure.
- Next pullback identifies `P3_2` (Bar 15).
- Set 2 forms: TJL1 = `CH_2` (Bar 12), TJL2 = `CL_1` (Bar 7), `P3_2` (Bar 15).

## 2. Acceptance Assertions
- **Case B (Confirmed Member Shared)**: `CL_1` (Bar 7) is an actual confirmed TJL member in BOTH Set 1 and Set 2.
- **Level ID Invariance**: Level ID `("FEED_EURUSD_H1", "H1", "2026-10-01T07:00:00Z", "LOW")` is identical across sets.
- **Usage Contract**: Any existing usage recorded on `CL_1` survives into Set 2 without resetting.
- **Case C (Cancellation Intent Contract)**: Set 2 replacement emits an outgoing cancellation intent that invalidates Set 1 as a whole, cancelling pending activations on Set 1 even though member `CL_1` survives into Set 2.
- Surviving member `CL_1` in Set 2 requires a fresh tap under Set 2.
