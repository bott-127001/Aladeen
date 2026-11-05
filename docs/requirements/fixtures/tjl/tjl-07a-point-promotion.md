# Fixture Specification: `tjl_07a_point_promotion_to_confirmed_tjl`

**Category**: end_to_end_msm_derived, source_settled  
**Scope**: Point Provenance Promotion (Case A)  

## 1. Description & Strategy Context
Demonstrates Case A: Point 7 was Tentative Low P3 in Set 1 (not a TJL zone in Set 1). At Bar 14 continuation break, Point 7 is confirmed as CL2 and first becomes a TJL member (TJL1) with low-side zone `[1.1400, 1.1400]`.

## 2. Acceptance Assertions
- `expected_level_id == ("FEED_GBPUSD_H1", "H1", "2026-10-01T07:00:00Z", "LOW")`.
- `status_in_set_1 == "TENTATIVE_P3_NOT_TJL_ZONE"`.
- `status_at_t1_continuation == "CONFIRMED_CL_FIRST_BECOMES_TJL1"`.
- Point identity is preserved continuously from tentative identification through confirmation and first TJL zone creation.
