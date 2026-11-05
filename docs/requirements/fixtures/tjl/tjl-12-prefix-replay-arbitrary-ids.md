# Fixture Specification: `tjl_12_prefix_consistency_and_arbitrary_source_ids`

**Category**: synthetic_lifecycle_specification, source_settled  
**Scope**: Replay Determinism & Feed Isolation  

## 1. Description & Strategy Context
Verifies that level identity and set fingerprints support arbitrary source feed IDs (e.g. `FEED_ALPHA_H4`, `DEMO_XAUUSD_D1`). Replaying identical candle prefixes produces identical outputs deterministically.
