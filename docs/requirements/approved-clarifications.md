# Approved Strategy Clarifications — Aladeen / TopG

Last Updated: 2026-11-05

> [!IMPORTANT]
> **Provenance & Authority Boundary**:
> This document records user approvals dated **4 November 2026**, as reported in the project artifact `aladin_topg_dashboard_e6a30e5e.plan.md` (*"Aladin TopG Dashboard — Revised Contract"*), retrieved from the TopG project by the reviewer.
> This is a record of previously approved clarifications, not new strategy decisions. It establishes the authoritative reconciliation baseline between original strategy documents and later approved clarifications.
> The original approval messages were not independently inspected; verbatim quotations or section details not present in the artifact are not fabricated.

---

## 1. Market Structure Marking (MSM) Clarifications

### EMPTY RANGE — Empty Tentative-Level Search Range
- **Problem**: When the user's search-start candle itself becomes the first candle of the first valid pullback pair, excluding both pullback candles leaves an empty range `[start, pullback_1)` with zero eligible candles for the tentative extreme.
- **Approved Decision**:
  - Skip the pullback pair that leaves an empty tentative-level search range.
  - Keep the original starting candle as the search reference and continue looking forward for the next valid pullback pair.
  - Do NOT invent a synthetic price level or silently advance the reference candle.

### OPEN-01 — Display-Only Trend Status vs. Marking Direction
- **Approved Decision**:
  - Trend status ("Upward trend", "Downward trend", "Trend not confirmed", "Marking [direction] structure") is **display-only**.
  - It is computed purely from the comparison of completed confirmed swing pairs.
  - It is evaluated separately from the active marking engine direction and does NOT trigger automated direction reversals or mode switching.

---

## 2. Multi-Timeframe & Zone Lifecycle Clarifications

### OPEN-02 — TJL Level Lifecycle & Trading Set Timing (t1 vs. t2)
- **Approved Decision**:
  - TJL labels appear at **t1**; the current trading set changes only at **t2**.
  - The exact definitions and lifecycle of t1/t2 require the detailed recorded specification before implementation; do not infer them from this summary.

### OPEN-03 — Invalidation Precedence at Shared Close
- **Approved Decision**:
  - At a shared candle close timestamp where both an invalidation/replacement and a potential entry signal occur, apply source invalidation/replacement **before** evaluating entry eligibility.
  - An old zone activation cannot execute an entry at that instant if its source level has just been invalidated or replaced.

### OPEN-04 — Candle Timestamp Intervals & Wick Boundaries
- **Approved Decision**:
  - Candle intervals are strictly half-open: `[open_time, close_time)`.
  - A level that becomes available or confirmed at the close cannot reach backward in time to claim that candle's earlier wick.
  - If the intra-bar sequence of events cannot be determined from available data, mark as `UNKNOWN_ORDER`; do not emit a speculative trade signal.

### OPEN-05 — Rearming After Out-of-Zone Cancellation
- **Approved Decision**:
  - When zone cancellation occurs while the market price is already observed outside the zone boundaries, the next observed price touch is rearmed.

### OPEN-06 — Single Price Basis & Physical Observation
- **Approved Decision**:
  - Use one configured price basis (Bid, Ask, or Mid as explicitly configured).
  - A touch requires an actual observed price print inside the inclusive zone boundaries `[lower_edge, upper_edge]`.
  - Never interpolate a geometric path between discrete candle/tick observations.

### OPEN-07 — Multiple Confirmation Evidence Consolidation
- **Approved Decision**:
  - When a single entry setup possesses both CHOCH and ISS confirmation evidence, record both confirmation identifiers on that single entry record.
  - Do NOT generate two duplicate or competing entry signals.

---

## 3. Configuration, Identity & Replay Semantics

### OPEN-08 — Independent Engine Configuration & Manual Start Validation
- **Approved Decision**:
  - Each strategy engine operates with its own starting reference candle and direction.
  - H1 source and H1 confirmation share one configuration and event stream unless the user configures them differently. This does not authorize silent starting-candle inheritance across distinct engine configurations.
  - No silent start-candle inheritance across engines or timeframes.
  - Absent or currently forming (unconfirmed) start candles must be strictly rejected.
  - Editing a starting candle creates a completely new, clean calculation run without merging or contaminating prior historical signals.

### OPEN-09 — Origin, Evidence Status & Immutable Signals
- **Approved Decision**:
  - Record the origin and evidence status of all calculated entities.
  - Rows with uncertain status are diagnostics only, not published trade signals.
  - Published signals are strictly immutable.
  - Corrections require a versioned replay starting from the prior valid dependency.
  - *Note*: Detailed replay semantics must be reconciled before engine implementation.

### OPEN-10 — Native MT5 Boundaries & Persisted Source Calendar
- **Approved Decision**:
  - Candle boundaries must use native MT5 bar open times.
  - Weekly boundary (Monday 00:00) is interpreted strictly within the persisted source calendar of the broker data feed.
  - Calculation identity includes: `(server, symbol, price_basis, timeframe_configuration, manual_start_time, rule_version)`.
  - Never infer the market calendar from the local computer's clock or timezone.

### OPEN-11 — Chronological Signal Listing Without Position Gating
- **Approved Decision**:
  - List every conceptual trade signal chronologically as it occurs, including subsequent opposite-side signals.
  - The analysis engine must not filter, suppress, or gate signals based on hypothetical open positions.

### OPEN-12 — Event Ordering at Coarse Timestamp T
- **Approved Decision**:
  - A later market event occurring at coarse timestamp T may rearm only after the winning entry commit has finalized.
  - *Note*: Detailed sequencing evidence must be formally specified before coding.

---

## 4. Operational Safety Boundary: Fail-Closed Principle

- **Block Only Missing Evidence**: In any composite transition, block only the specific transition branch that lacks necessary evidence. Do not freeze independent transitions.
- **Immediate Invalidation**: Finalized source invalidation or replacement immediately cancels affected eligibility.
- **Strict Non-Emission**: Unknown event ordering, incomplete candle batches, unverified coverage, or lack of an observed touch print must NOT emit a signal, consume a level, or rearm eligibility.
