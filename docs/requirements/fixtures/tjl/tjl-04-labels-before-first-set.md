# Fixture Specification: `tjl_04_labels_before_first_eligible_set`

**Category**: end_to_end_msm_derived, source_settled  
**Scope**: Label Availability vs. Current Set Trading Eligibility  

## 1. Description & Strategy Context
Prefix evaluation of `tjl_01` at Bar 4. MSM confirms Confirmed High (Bar 1) and Confirmed Low (Bar 4). Both points receive TJL labels immediately upon confirmation.

## 2. Acceptance Assertions
- `labeled_points_count == 2` (TJL1 and TJL2 are labeled and visible).
- `active_p3 == None` (no valid pullback has completed yet).
- `current_set == None` (no eligible trading set exists).
- `is_eligible_for_trading == False`.
- **Core Strategy Rule**: Labels alone are NOT an eligible trading set; trading eligibility strictly requires an active P3.
