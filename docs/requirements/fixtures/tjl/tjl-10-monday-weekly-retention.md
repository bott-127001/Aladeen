# Fixture Specification: `tjl_10_monday_weekly_retention_without_reset`

**Category**: synthetic_lifecycle_specification, source_settled  
**Scope**: Monday Weekly Review & Retention Invariance  

## 1. Description & Strategy Context
Monday 00:00 boundary arrives without a new 3-point set forming over the weekend or on the opening bar.

## 2. Acceptance Assertions (MTF Analysis Section 4 & OPEN-10)
- `is_set_retained == True` (existing set remains current and active).
- Monday alone does NOT delete a level, replace a set, cancel an activation, or reset used status.
- A level marked used before Monday remains used after Monday (`was_usage_reset == False`).
- Native MT5 broker calendar is used; local computer timezone is never inferred.
