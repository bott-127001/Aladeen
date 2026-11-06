# Tap and Zone Activation — Acceptance Specification

Last Updated: 2026-11-06

> [!IMPORTANT]
> **Specification Authority & Provenance**:
> - **Primary Multi-Timeframe & Activation Source**: `docs/strategy/MTF-Analysis.pdf` (Version 1 — Consolidated rule record, 26 October 2026, 12:58 AM IST), transcribing `Entry_and_Confirmation_New_Rules.pdf` with approved user decisions.
>   - *Section 5*: Tap and Activation (Any wick touch activates; close inside not required; first tap starts search; repeated taps do not reset; tap is not an entry signal).
>   - *Section 8*: Competing Activations and Tie-Breakers (First confirmation by close timestamp wins; simultaneous close chooses lower timeframe; simultaneous same-timeframe chooses TJL2 / A+; winning entry marks level used and cancels all other pending activations).
>   - *Section 9*: Cancellation and Reactivation (Replacement TJL set cancels old set; source main CHOCH immediately cancels old-direction activation; external entry cancels pending activations; price must leave zone and retouch to reactivate; used level cannot reactivate).
>   - *Section 10*: One Trade Per Level (Each particular level supplies at most one trade; touch is not usage; entry commit is usage; repeated taps, cancellations, and Monday resets do not reset used status).
>   - *Section 12*: Q&A Record (Questions 2, 5, 10, 11, 13, 16, 17, 21, 22, 24, 25).
> - **Approved Clarifications Authority**: [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (User approvals dated 4 November 2026, recorded in project artifact `aladin_topg_dashboard_e6a30e5e.plan.md`):
>   - `OPEN-03`: Invalidation Precedence at Shared Close (Source invalidation/replacement applied before evaluating entry eligibility).
>   - `OPEN-04`: Candle Timestamp Intervals & Wick Boundaries (Half-open intervals `[open_time, close_time)`; level cannot retroactively claim earlier candle wick; unknown ordering marks `UNKNOWN_ORDER`).
>   - `OPEN-05`: Rearming After Out-of-Zone Cancellation (When cancellation occurs while price is observed outside zone, next observed touch rearms).
>   - `OPEN-06`: Single Price Basis & Physical Observation (Configured Bid/Ask/Mid; actual observed print inside `[lower, upper]`; zero path interpolation).
>   - `OPEN-08`: Independent Engine Configuration & Manual Start Validation (Isolated runs; no silent start inheritance; clean calculation runs).
>   - `OPEN-09`: Origin, Evidence Status & Immutable Signals (Immutable published records; versioned replay from prior valid dependency).
>   - `OPEN-10`: Native MT5 Boundaries & Persisted Source Calendar (Native MT5 bar times; weekly boundary within broker source calendar).
>   - `OPEN-12`: Event Ordering at Coarse Timestamp T (Later event rearms only after winning entry commit finalizes).
> - **Prerequisite Specifications**:
>   - [`docs/requirements/msm-acceptance.md`](msm-acceptance.md) (Market Structure Marking)
>   - [`docs/requirements/tjl-acceptance.md`](tjl-acceptance.md) (Trend Joining Level)
>   - [`docs/requirements/choch-acceptance.md`](choch-acceptance.md) (Change of Character)
>   - [`docs/requirements/iss-acceptance.md`](iss-acceptance.md) (Internal Structure Shift)
> - **Strict Safety & Scope Boundary**: Pure requirements specification and machine-readable fixture integrity validation. Strictly **zero activation engine implementation, zero usage ledger, zero arbitration logic, zero trade entry signals, zero order execution, and zero live account modification**.

---

## 1. Scope, Purpose, and Framework

The Tap and Zone Activation subsystem bridges higher-timeframe Trend Joining Levels (TJL) with lower-timeframe entry confirmation (CHOCH / ISS).
- **TJL Supplies the Structural Levels**: D1, H4, and H1 source timeframes qualify structural levels (`tjl1_zone` and `tjl2_zone`).
- **Price Decides via Tap**: Price tapping an unused, currently eligible TJL zone begins a confirmation search on the designated confirmation timeframe:
  - **D1 Source** $\rightarrow$ **H1 Confirmation**
  - **H4 Source** $\rightarrow$ **M5 Confirmation**
  - **H1 Source** $\rightarrow$ **M1 Confirmation**
- **Tap Is NOT an Entry Signal**: A tap only transitions a level from `INACTIVE_ELIGIBLE` to `PENDING_ACTIVATION`. Entry occurs strictly when a qualifying pattern confirms on the lower timeframe on or after the tap candle.
- **One Trade Per Level**: Each physical level can supply at most one trade in its lifetime. Taps, cancellations, and weekly roll-overs do not consume a level; only an accepted winning entry marks a level `USED`.

---

## 2. Separation of Architectural Concerns

To prevent architectural contamination and enforce strict boundaries across modules, the activation lifecycle is separated into six distinct concerns:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Source Structural Eligibility (TJL Engine: D1, H4, H1)             │
│    - Current Eligible Set membership (SET_1, SET_2)                    │
│    - eligibility_available_time established                            │
│    - Non-current labels in all_labeled_zones are INELIGIBLE            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Provides CurrentEligibleSet
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Observed Touch Evidence (Price Feed / Market Ingestion)             │
│    - Single price basis (Bid, Ask, Mid) [OPEN-06]                      │
│    - Time constraint: event_time >= eligibility_available_time [OPEN-04]│
│    - Zero geometric path interpolation [OPEN-06]                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Emits TouchObservation
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Pending Activation Lifecycle (Activation Subsystem)                 │
│    - First touch -> PENDING_ACTIVATION (Starts confirmation search)    │
│    - Repeated touches -> REPEATED_OBSERVATION (No reset of search)     │
│    - Source t2 replacement -> CANCELLED_SOURCE_REPLACEMENT             │
│    - Source main CHOCH -> CANCELLED_SOURCE_CHOCH                       │
│    - Out-of-zone departure -> REARMED_READY (if cancelled & unused)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Tracks PendingActivations
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│ 4. Future Confirmation & Arbitration │  │ 5. Future Usage Ledger       │
│    - Lower TF pattern ingestion      │  │    - One trade per level     │
│    - Earliest close timestamp wins   │  │    - Winning entry consumes  │
│    - Tie-breakers: lower TF, TJL2    │  │    - StableLevelId identity  │
│    - Cancels other pending sets      │  │    - Retained used level dead│
└──────────────────────────────────────┘  └──────────────────────────────┘
```

### 2.1 Source-Level Structural Eligibility
Structural eligibility is governed exclusively by the source TJL Engine:
1. **Set Membership**: Only zones belonging to the active `CurrentEligibleSet` (`tjl1_zone` or `tjl2_zone`) can be activated.
2. **Known Availability Required**:
   - `eligibility_available_time` must be an explicit, timezone-aware UTC timestamp.
   - If `eligibility_available_time is None` (e.g. formed from unconfirmed candle or stripped close times), the zone is structurally **ineligible** for time-extended tap activation.
3. **Labels-Only Exclusion**: Labeled zones awaiting set formation (e.g. prefix before first Point 3, or following continuation break) are not in the current eligible set and **cannot** be activated.
4. **Historical Set Exclusion**: Zones from superseded or cancelled historical sets cannot be activated.

### 2.2 Observed Touch Evidence
Touch observation converts raw market data into physical evidence:
1. **Inclusive Price Boundary**: Any wick touch or penetration counts. An event touches zone `[lower_price, upper_price]` if:
   $$\text{low} \le \text{upper\_price} \quad \text{and} \quad \text{high} \ge \text{lower\_price}$$
   For a zero-width line zone (`lower_price == upper_price`):
   $$\text{low} \le \text{lower\_price} \le \text{high}$$
2. **Strict Half-Open Interval Timing (`OPEN-04`)**:
   - Candle intervals are strictly half-open: `[open_time, close_time)`.
   - A touch observation is valid if and only if:
     $$\text{event\_time} \ge \text{eligibility\_available\_time}$$
   - Earlier candles or wicks occurring before `eligibility_available_time` **cannot** be claimed retroactively.
3. **Single Price Basis (`OPEN-06`)**:
   - Calculations use one configured price basis (Bid, Ask, or Mid).
   - Touch evidence requires an actual observed price print within the boundaries.
   - No speculative path interpolation between candles or ticks is permitted.

### 2.3 Pending Activation Lifecycle
Once a valid touch is observed on an eligible, unused level:
1. **First Activation**:
   - Transitions level state to `PENDING_ACTIVATION`.
   - Maps the source timeframe to its confirmation timeframe (D1 $\rightarrow$ H1, H4 $\rightarrow$ M5, H1 $\rightarrow$ M1).
   - Starts monitoring for newly confirmed CHOCH or ISS patterns on that lower timeframe.
2. **Repeated Touches (`MTF-Analysis.pdf` Section 5)**:
   - Further price touches while an activation is already pending do **not** restart, reset, or delay the confirmation search.
   - Recorded as `REPEATED_OBSERVATION` diagnostic events; original activation start timestamp is preserved.
3. **No Entry Signal on Tap**: A tap does not generate an entry signal, place an order, or allocate risk.

### 2.4 Cancellation and Invalidation Precedence
Pending activations are cancelled by specific lifecycle events:
1. **Source Set Replacement (t2)**: When the source timeframe completes a pullback and qualifies a new `CurrentEligibleSet` (`SET_2`), pending activations on `SET_1` are cancelled immediately (`CANCELLED_SOURCE_REPLACEMENT`). The replacement set requires its own tap.
2. **Source Main CHOCH**: When the source timeframe experiences main CHOCH, all pending activations in the old direction are cancelled immediately (`CANCELLED_SOURCE_CHOCH`), even before replacement TJLs form.
3. **External Winning Entry**: When a trade is accepted from any active level (on any timeframe), all other pending activations across D1, H4, and H1 are cancelled (`CANCELLED_EXTERNAL_ENTRY`).
4. **Shared Close Invalidation Precedence (`OPEN-03`)**: At a candle close where both source invalidation/replacement and a potential confirmation signal occur, invalidation is evaluated **first**. An invalidated or replaced level cannot produce an entry.

### 2.5 Rearming After Out-of-Zone Cancellation (`OPEN-05`, `MTF-Analysis.pdf` Section 9)
An unused level cancelled due to an external winning entry may reactivate if still structurally eligible:
1. **Zone Departure Required**: Price must be observed strictly outside the zone boundaries (`high < lower_price` or `low > upper_price`). Remaining inside the zone does not qualify.
2. **Fresh Tap Required**: After leaving the zone, a new observed touch re-arms the activation (`REARMED_PENDING`).
3. **Fresh Confirmation Required**: The reactivated level requires a fresh qualifying confirmation on or after the new tap candle; prior completed patterns cannot be reused.
4. **Source Replaced or Invalidated Levels Never Rearm**: Levels superseded by replacement (t2) or invalidated by source CHOCH cannot rearm.

---

## 3. Future Module Interface Contracts (Read-Only Declarations)

To prevent premature coupling, this specification formally documents the interface contracts required by future arbitration and ledger modules without implementing them:

### 3.1 Confirmation Pattern Protocol (Lower Timeframe Engine)
A future confirmation engine provides confirmed pattern events matching this interface:
```python
class ConfirmationPatternEvent:
    event_id: str                      # Unique event ID
    timeframe: str                     # H1, M5, M1
    pattern_type: str                  # "CHOCH" | "ISS"
    direction: Direction               # UPWARD (Buy) | DOWNWARD (Sell)
    pattern_start_time: datetime       # Pattern inception timestamp (can be before tap)
    confirmation_close_time: datetime  # Exact completed close time (MUST be >= tap_time)
```

### 3.2 Arbitration Tie-Breaker Protocol (`MTF-Analysis.pdf` Section 8)
When multiple activations are pending simultaneously:
1. **Chronological Primary**: Earliest `confirmation_close_time` wins.
2. **Simultaneous Timestamp Tie-Breaker 1 (Timeframe Precedence)**:
   $$\text{M1} \succ \text{M5} \succ \text{H1}$$
3. **Simultaneous Timestamp Tie-Breaker 2 (TJL Role Precedence)**:
   $$\text{TJL2 / A+} \succ \text{TJL1}$$
4. **Cancellation Trigger**: The winning setup triggers cancellation of all competing pending activations.

### 3.3 Usage Ledger Protocol (`MTF-Analysis.pdf` Section 10)
A future usage ledger tracks level consumption:
```python
class LevelUsageRecord:
    level_id: StableLevelId            # Physical level identity
    used_status: bool                  # True if a trade was taken from this level
    usage_commit_time: datetime | None # Timestamp when entry was committed
    winning_event_id: str | None       # Provenance link to winning entry
```
- **Rule**: If `used_status is True`, the level is permanently ineligible for activation across all future cycles, sets, and Monday roll-overs.

---

## 4. Input & Evidence Contracts

All activation-acceptance fixtures and future implementations adhere to these immutable value contracts:

### 4.1 Structural Level Reference
```python
@dataclass(frozen=True)
class ActivationSourceLevel:
    engine_id: str                     # Unique engine run identifier
    symbol: str                        # Market symbol (e.g. EURUSD)
    source_timeframe: str              # D1, H4, H1
    set_id: str                        # SET_1, SET_2
    level_id: StableLevelId            # Unique physical level identifier
    role: TJLLabel                     # TJL1, TJL2_A_PLUS
    side: TJLSide                      # HIGH, LOW
    lower_edge: float                  # Inclusive lower price bound
    upper_edge: float                  # Inclusive upper price bound
    is_line: bool                      # True if lower_edge == upper_edge
    eligibility_available_time: datetime | None  # Start of structural eligibility
    direction: Direction               # Expected trade direction
```

### 4.2 Observed Market Event
```python
@dataclass(frozen=True)
class ObservedPriceEvent:
    event_id: str                      # Deterministic sequence identifier
    time: datetime                     # Half-open candle open time or tick time
    close_time: datetime               # Candle close time
    open: float
    high: float
    low: float
    close: float
    price_basis: str                   # "BID" | "ASK" | "MID"
```

### 4.3 Activation State Machine
```
[ INACTIVE_ELIGIBLE ]
        │
        ├─ Event: touch_observed (event_time >= eligibility_available_time)
        ▼
[ PENDING_ACTIVATION ] ◄─── (Repeated touches logged as REPEATED_OBSERVATION)
        │
        ├─ Event: source_choch_invalidated ───► [ CANCELLED_SOURCE_CHOCH ] (Permanent)
        ├─ Event: source_set_replaced ────────► [ CANCELLED_SOURCE_REPLACEMENT ] (Permanent)
        ├─ Event: external_entry_committed ───► [ CANCELLED_EXTERNAL_ENTRY ] (Unused)
        │                                              │
        │                                              ├─ Event: price_leaves_zone
        │                                              ▼
        │                                       [ OUT_OF_ZONE_ARMED ]
        │                                              │
        │                                              ├─ Event: fresh_touch_observed
        │                                              ▼
        └─────────────────────────────────────── [ REARMED_PENDING ]
```

---

## 5. Acceptance Fixture Categories

The machine-readable acceptance suite in `tests/fixtures/activation_acceptance.json` contains 10 deterministic test categories covering all approved rules:

| Category ID | Scenario Name | Primary Authority | Key Assertions & Invariants |
|---|---|---|---|
| **`ACT_01`** | Known Availability First Touch | `MTF-Analysis.pdf` §5 | Touch at $t \ge t_{\text{avail}}$ transitions level to `PENDING_ACTIVATION`; maps confirmation timeframe. |
| **`ACT_02`** | Unknown Availability Blocks Activation | `docs/strategy/approved-clarifications.md` §4 | `eligibility_available_time is None` blocks time-extended activation; fails closed. |
| **`ACT_03`** | No Retroactive Wick Claim | `OPEN-04` | Touch occurring in candle interval prior to `eligibility_available_time` is rejected; only subsequent touch activates. |
| **`ACT_04`** | Observed Touch vs Path Inference | `OPEN-06` | Boundary touches count (`low <= upper and high >= lower`); path interpolation between non-touching candles rejected. |
| **`ACT_05`** | Repeated Observations No Reset | `MTF-Analysis.pdf` §5 | Secondary and tertiary touches while pending do not reset `first_touch_time` or restart search. |
| **`ACT_06`** | Source CHOCH Cancellation | `MTF-Analysis.pdf` §9, `OPEN-03` | Source main CHOCH immediately cancels pending activation; status becomes `CANCELLED_SOURCE_CHOCH`. |
| **`ACT_07`** | Source t2 Replacement Cancellation | `MTF-Analysis.pdf` §9 | Pullback t2 replacement cancels SET_1 activation; new SET_2 requires independent touch. |
| **`ACT_08`** | External Entry Cancellation & Rearm | `MTF-Analysis.pdf` §8–10, `OPEN-05` | External entry cancels pending activation without consuming level; price leaves zone and retouches, successfully rearming. |
| **`ACT_09`** | Same-Time Invalidation Precedence | `OPEN-03`, `OPEN-12` | Invalidation at shared close timestamp evaluated before entry; invalidated level cannot produce entry. |
| **`ACT_10`** | Configuration Isolation & Replay | `OPEN-08`, `OPEN-09` | Independent engine runs isolated; idempotent replay reproduces identical activation sequence. |

---

## 6. Verification Boundaries & Non-Invention Policy

1. **Pure Requirements Baseline**: This document and its accompanying fixtures define the *criteria for acceptance* of any future activation engine.
2. **No Execution or Trading**: Activation does not place orders, verify margin, route requests, or compute lot sizes.
3. **No Missing Price-Path Invention**: If tick-level intra-bar price sequence is absent, candle wicks are evaluated strictly within declared timestamps; no speculative tick paths are inferred.
4. **Non-Settlement of Core Ambiguities**: Acceptance of these activation requirements does not settle upstream unresolved questions ($c_1 == p_2$ boundary or ISS multi-candle pullbacks).
