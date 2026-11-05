# Fixture Specification: `tjl_07_persistent_level_identity_across_replacement`

**Category**: end_to_end_msm_derived, source_settled  
**Scope**: Stable Level Identity Formula & Replacement Invariance  

## 1. Description & Strategy Context
Demonstrates the engineering level identity formula:
$$\text{Level ID} = (\text{symbol\_feed\_id},\, \text{source\_timeframe},\, \text{source\_open\_time},\, \text{HIGH} \mid \text{LOW})$$

Point CL at Bar 7 was the tentative low P3 in Set 1, and carries forward as Confirmed Low TJL1 in Set 2.

## 2. Acceptance Assertions
- `Level ID` is identical across Set 1 and Set 2: `("FEED_GBPUSD_H1", "H1", "2026-10-01T07:00:00Z", "LOW")`.
- Role name, week, activation ID, and set ID are strictly excluded from `Level ID`.
- Relabeling or re-observation never creates a fresh level.
- Used status on a persistent level never resets.
- Outgoing cancellation intent applies to Set 1 as a whole despite member level carry-forward.
