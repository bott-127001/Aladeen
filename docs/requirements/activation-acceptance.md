# Tap and Zone Activation — Acceptance Specification

Last Updated: 2026-11-06

> [!IMPORTANT]
> **Specification Authority & Provenance**:
> - **Primary Multi-Timeframe & Activation Source**: `docs/strategy/MTF-Analysis.pdf` (Version 1 — Consolidated rule record, 26 October 2026, 12:58 AM IST), transcribing `Entry_and_Confirmation_New_Rules.pdf` with approved user decisions.
>   - *Section 3*: Source Timeframes, Structure and Direction (D1, H4, H1; TJL1 and TJL2 follow trend; same activation rule for both).
>   - *Section 5*: Tap and Activation (Any wick touch activates; close inside not required; first tap starts search; repeated taps do not reset; tap is not an entry signal).
>   - *Section 6*: Confirmation Mapping and Direction (D1 $\rightarrow$ H1, H4 $\rightarrow$ M5, H1 $\rightarrow$ M1; normal CHOCH or ISS).
>   - *Section 8*: Competing Activations and Tie-Breakers (First confirmation by close timestamp wins; simultaneous close chooses lower timeframe; simultaneous same-source chooses TJL2 / A+; winning entry marks level used and cancels all other pending activations).
>   - *Section 9*: Cancellation and Reactivation (Replacement TJL set cancels old set; source main CHOCH immediately cancels old-direction activation; external entry cancels pending activations; price must leave zone and retouch to reactivate; used level cannot reactivate).
>   - *Section 10*: One Trade Per Level (Each particular level supplies at most one trade; touch is not usage; entry commit is usage; repeated taps, cancellations, and Monday resets do not reset used status).
>   - *Section 12*: Q&A Record (Questions 2, 3, 5, 10, 11, 13, 15, 16, 17, 18, 20, 21, 22, 24, 25).
> - **Approved Clarifications Authority**: [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (User approvals dated 4 November 2026, recorded in project artifact `aladin_topg_dashboard_e6a30e5e.plan.md`):
>   - `OPEN-03`: Invalidation Precedence at Shared Close (Source invalidation/replacement applied before evaluating entry eligibility).
>   - `OPEN-04`: Candle Timestamp Intervals & Wick Boundaries (Half-open intervals `[open_time, close_time)`; level cannot retroactively claim earlier candle wick; unknown ordering marks `UNKNOWN_ORDER`).
>   - `OPEN-05`: Rearming After Out-of-Zone Cancellation (When cancellation occurs while price is observed outside zone, next observed touch rearms).
>   - `OPEN-06`: Single Price Basis & Physical Observation (Configured Bid/Ask/Mid; actual observed print inside `[lower, upper]`; zero path interpolation).
>   - `OPEN-08`: Independent Engine Configuration & Manual Start Validation (Isolated runs; no silent start inheritance; clean calculation runs).
>   - `OPEN-09`: Origin, Evidence Status & Immutable Signals (Immutable published records; versioned replay from prior valid dependency).
>   - `OPEN-10`: Native MT5 Boundaries & Persisted Source Calendar (Native MT5 bar times; weekly boundary within broker source calendar).
>   - `OPEN-12`: Event Ordering at Coarse Timestamp T (Later event rearms only after winning entry commit finalizes).
> - **Prerequisite Strategy Specifications**:
>   - [`docs/requirements/msm-acceptance.md`](msm-acceptance.md) (Market Structure Marking)
>   - [`docs/requirements/tjl-acceptance.md`](tjl-acceptance.md) (Trend Joining Level)
>   - [`docs/requirements/choch-acceptance.md`](choch-acceptance.md) (Change of Character)
>   - [`docs/requirements/iss-acceptance.md`](iss-acceptance.md) (Internal Structure Shift)
> - **Strict Safety & Scope Boundary**: Pure requirements specification and machine-readable fixture integrity validation. Strictly **zero activation engine implementation, zero usage ledger, zero arbitration logic, zero trade entry signals, zero order execution, and zero live account modification**.

---

## 1. Scope, Purpose, and Framework

The Tap and Zone Activation subsystem bridges higher-timeframe Trend Joining Levels (TJL) with lower-timeframe entry confirmation (CHOCH / ISS).
- **TJL Supplies the Structural Levels**: D1, H4, and H1 source timeframes independently qualify structural levels (`tjl1_zone` and `tjl2_zone`). Both members of an active set may be activated independently.
- **Price Decides via Tap**: Price physically printing inside an unused, currently eligible TJL zone begins a confirmation search on the designated confirmation timeframe:
  - **D1 Source** $\rightarrow$ **H1 Confirmation**
  - **H4 Source** $\rightarrow$ **M5 Confirmation**
  - **H1 Source** $\rightarrow$ **M1 Confirmation**
- **Tap Is NOT an Entry Signal**: A tap only transitions a level from `INACTIVE_ELIGIBLE` to `PENDING_ACTIVATION`. Entry occurs strictly when a qualifying pattern confirms on the lower timeframe on or after the tap candle.
- **One Trade Per Level**: Each physical level (`StableLevelId`) can supply at most one trade in its lifetime. Taps, cancellations, repeated observations, and weekly roll-overs do not consume a level; only an accepted winning entry marks a level `USED`.

---

## 2. Separation of Architectural Concerns & Core Rules

To prevent domain confusion and enforce strict isolation across subsystems, the activation lifecycle is governed by explicit rules and engineering contracts:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Source Structural Eligibility (TJL Engine: D1, H4, H1)             │
│    - Current Eligible Set membership (SET_1, SET_2)                    │
│    - Unknown availability blocks activation evidence, not membership   │
│    - At t1, old current set remains eligible; next labels ineligible   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Provides CurrentEligibleSet
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Observed Print Evidence (Market Data Ingestion)                     │
│    - Observed price print p in [lower, upper] (not range overlap)      │
│    - Single configured price basis (Bid, Ask, Mid) [OPEN-06]           │
│    - Zero geometric path interpolation [OPEN-06]                       │
│    - Half-open interval timing: t >= eligibility_available_time [OPEN-04]│
│    - Blocked: UNKNOWN_ORDER, UNKNOWN_COVERAGE, NO_OBSERVED_TOUCH       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Emits TouchObservation
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Pending Activation Lifecycle (Activation Subsystem)                 │
│    - First touch -> PENDING_ACTIVATION (Starts confirmation search)    │
│    - Repeated touches -> REPEATED_OBSERVATION (No reset of search)     │
│    - Source t2 replacement -> CANCELLED_SOURCE_REPLACEMENT             │
│    - Source main CHOCH -> CANCELLED_SOURCE_CHOCH                       │
│    - Rearming (OPEN-05):                                               │
│        * Already outside at cancellation -> next touch rearms          │
│        * Inside at cancellation -> later outside print -> fresh touch  │
│        * Lingering inside -> blocked (no rearming)                     │
│    - Replay idempotence & event ordering at coarse timestamp T [OPEN-12]│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Tracks PendingActivations
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│ 4. Future Confirmation & Arbitration │  │ 5. Future Usage Ledger       │
│    - Lower TF pattern ingestion      │  │    - One trade per level     │
│    - Earliest close timestamp wins   │  │    - Winning entry consumes  │
│    - Tie-breakers: lower TF, TJL2    │  │    - StableLevelId identity  │
│    - Scoped TJL2/A+ to same source   │  │    - Retained used level dead│
└──────────────────────────────────────┘  └──────────────────────────────┘
```

### 2.1 Source-Level Structural Eligibility
- **RULE [Structural Membership]**: A level is structurally eligible for activation if and only if it is a confirmed member of the active `CurrentEligibleSet` (`tjl1_zone` or `tjl2_zone`) produced by the source TJL coordinator.
- **RULE [Both Members Independently Active]**: Both `tjl1_zone` and `tjl2_zone` of an active current set may receive taps and hold `PENDING_ACTIVATION` states concurrently. There is no restriction limiting a source timeframe to a single pending activation (`MTF-Analysis.pdf` §8, Q&A 22).
- **RULE [Continuation t1 Eligibility]**: At transition `t1` (continuation), the existing current set is retained and remains fully eligible for activation. Only the newly confirmed next-set labels in `all_labeled_zones` are structurally ineligible (`docs/requirements/tjl-acceptance.md` §5.2).
- **RULE [Labels-Only Exclusion]**: Zones in `all_labeled_zones` that do not belong to the current eligible set (e.g. prefix before first Point 3, or awaiting set replacement) are structurally ineligible for activation.
- **ENGINEERING CONTRACT [Unknown Availability]**: If `eligibility_available_time is None` (e.g. stripped candle close times), the level retains structural set membership in the engine, but activation evidence is blocked: no time-extended interval or tap activation can occur (fail-closed principle).

### 2.2 Observed Price Print Evidence vs. Range Overlap
- **RULE [OPEN-06: Physical Observation vs. Range Overlap]**:
  - A touch requires an actual observed price print $p$ on the single configured price basis (Bid, Ask, or Mid) such that:
    $$\text{lower\_edge} \le p \le \text{upper\_edge}$$
  - For an exact zero-width line level (`lower_edge == upper_edge`):
    $$p = \text{lower\_edge}$$
  - **Range Overlap Is Insufficient**: A candle whose high/low range straddles a zone ($\text{low} < \text{lower}$ and $\text{high} > \text{upper}$) without any recorded print ($open, high, low, close$) in $[\text{lower}, \text{upper}]$ represents a candidate intersection, NOT an observed touch. Discrete prices can gap over or skip a zone.
  - **Zero Geometric Path Interpolation**: No continuous price path between discrete ticks or candle bars may be assumed or interpolated.
- **RULE [What OHLC Proves vs. What It Does Not Prove]**:
  1. *Open Price*: Proves price printed at $p = \text{open}$ at timestamp $t = \text{open\_time}$.
  2. *Close Price*: Proves price printed at $p = \text{close}$ at timestamp $t = \text{close\_time}$.
  3. *High/Low Extremes*: A recorded extreme $p \in [\text{lower}, \text{upper}]$ proves price touched the zone at *some* instant during the half-open interval $[t_{\text{open}}, t_{\text{close}})$, but DOES NOT prove its exact intra-bar timestamp or sequence relative to intra-bar boundary events.
- **RULE [OPEN-04: Intra-Bar Timing & No Retroactive Wick Claims]**:
  - A touch observation is valid if and only if the physical print occurred at $t \ge \text{eligibility\_available\_time}$.
  - Wicks occurring during candle intervals strictly prior to `eligibility_available_time` cannot be claimed retroactively.
  - If `eligibility_available_time` falls *inside* a candle interval $[t_{\text{open}}, t_{\text{close}})$:
    - If Open is after or at availability and prints in the zone: valid touch at $t_{\text{open}}$.
    - If Close prints in the zone: valid touch at $t_{\text{close}}$.
    - If only a wick touches the zone and intra-bar tick sequence is unavailable to prove whether the wick occurred before or after availability, the transition is blocked as `UNKNOWN_ORDER` (fail-closed).
- **ENGINEERING CONTRACT [Blocked Evidence Categories]**:
  - `NO_OBSERVED_TOUCH`: High/low range straddles zone but no discrete print inside.
  - `UNKNOWN_ORDER`: Intra-bar event sequence cannot be proven relative to availability or invalidation.
  - `UNKNOWN_COVERAGE`: Incomplete batch, missing candles, or uncertain data feed coverage.

### 2.3 Pending Activation Lifecycle
- **RULE [First Activation]**: The first valid observed touch transitions an unused, eligible level from `INACTIVE_ELIGIBLE` to `PENDING_ACTIVATION`, establishing `first_touch_time` and assigning the mapped confirmation timeframe:
  - D1 $\rightarrow$ H1
  - H4 $\rightarrow$ M5
  - H1 $\rightarrow$ M1
- **RULE [Repeated Observations Do Not Reset Search]**: Subsequent observed touches while an activation is already pending are recorded as `REPEATED_OBSERVATION` diagnostic events. They do NOT restart, reset, or delay the confirmation search (`MTF-Analysis.pdf` §5, Q&A 13).
- **RULE [Tap Is Not an Entry Signal]**: An activation does not place an order, calculate lot size, verify margin, or emit a trade entry.

### 2.4 Cancellation and Precedence
- **RULE [Source Replacement Cancellation]**: When the source timeframe completes a pullback and qualifies a new `CurrentEligibleSet` (`SET_2`), pending activations on `SET_1` are immediately cancelled (`CANCELLED_SOURCE_REPLACEMENT`). The replacement set requires its own tap.
- **RULE [Source Main CHOCH Cancellation]**: When the source timeframe experiences main CHOCH, all pending activations in the old direction are cancelled immediately (`CANCELLED_SOURCE_CHOCH`), even before replacement TJLs form.
- **RULE [External Winning Entry Cancellation]**: When a trade is accepted from any active level across any timeframe, all other pending activations across D1, H4, and H1 are cancelled (`CANCELLED_EXTERNAL_ENTRY`). Cancelled levels remain `used_status = False`.
- **RULE [OPEN-03: Shared-Close Invalidation Precedence]**: At a candle close where both source invalidation/replacement and a potential entry confirmation occur, source invalidation is evaluated **first**. An invalidated or replaced level cannot execute an entry at that timestamp.
- **ENGINEERING CONTRACT [Fail-Closed Scoping]**: In composite transitions, fail closed only for the specific transition branch lacking necessary evidence. A finalized source invalidation or replacement remains effective even if unrelated touch or confirmation evidence is unresolved elsewhere.

### 2.5 Rearming Semantics (OPEN-05)
An unused level whose activation was cancelled by an external winning entry may reactivate if it remains a member of the current eligible set:
- **RULE [OPEN-05 Path A: Cancelled While Observed Inside]**:
  - If the market price is observed inside the zone boundaries at the moment of cancellation:
  - Price must subsequently be observed strictly outside the zone (`high < lower_edge` or `low > upper_edge`).
  - Only after an outside observation has been established does a fresh observed touch transition the level to `REARMED_PENDING`.
- **RULE [OPEN-05 Path B: Cancelled While Already Observed Outside]**:
  - If the market price is already observed strictly outside the zone boundaries at the moment of cancellation:
  - The level is immediately armed for the next later observed touch without requiring an additional departure.
  - The next valid observed touch transitions the level to `REARMED_PENDING`.
- **RULE [Lingering Inside Blocks Rearming]**: Remaining inside the zone after cancellation without a confirmed outside observation does NOT rearm the level.
- **RULE [Unknown Outside State Blocks Rearming]**: If price position relative to the zone cannot be established, rearming is blocked (no speculative arming).
- **RULE [Fresh Confirmation Required]**: A reactivated level requires a fresh qualifying confirmation on or after the new tap candle; prior completed patterns cannot be reused.

### 2.6 Terminal Activation vs. Persistent Physical Level Identity
- **ENGINEERING CONTRACT [Transient Activation Object]**: An activation is a transient lifecycle state machine tied to `(set_id, role, first_touch_time)`. When cancelled, that specific activation record is terminal and cannot revive.
- **ENGINEERING CONTRACT [Persistent Physical Level Identity]**:
  - Physical levels are identified by immutable engineering formula:
    $$\text{StableLevelId} = (\text{symbol\_feed\_id}, \text{source\_timeframe}, \text{source\_open\_time}, \text{HIGH} \mid \text{LOW})$$
  - A physical level may survive into a replacement set (e.g. Case B/C persistent member) or reappear in a future structural epoch.
  - Surviving physical levels retain their identity and lifetime usage status.
  - **No Activation Inheritance**: A surviving unused level in a new set does NOT inherit pending activation from the replaced set. It requires its own independent touch under the new set to activate.

### 2.7 Event Ordering at Coarse Timestamp T (OPEN-12)
- **RULE [OPEN-12 Sequencing]**: A later market event occurring at coarse timestamp $T$ may rearm an activation only *after* the winning entry commit has finalized in the event stream:
  $$\text{event\_order}(\text{winning\_commit}) < \text{event\_order}(\text{rearm\_event})$$
- **RULE [No Recycled Evidence]**: A rearming event at timestamp $T$ cannot recycle the tap or confirmation evidence that competed with the winning entry.
- **ENGINEERING CONTRACT [Causal Order vs. Clock Order]**: Event ordering is established by explicit discrete event sequence or causal transaction order, never by local computer clock, callback scheduling, or function execution order.

---

## 3. Future Module Interface Contracts (Read-Only Declarations)

To ensure seamless downstream integration without premature implementation, this specification defines the explicit read-only protocols required by future arbitration and usage ledger subsystems:

### 3.1 Confirmation Pattern Protocol (Lower Timeframe Ingestion)
```python
@dataclass(frozen=True)
class ConfirmationPatternEvent:
    """Read-only confirmed pattern event emitted by lower-timeframe detection engines."""
    event_id: str                      # Unique event identifier
    timeframe: str                     # H1, M5, M1
    pattern_type: str                  # "CHOCH" | "ISS"
    direction: Direction               # UPWARD (Buy) | DOWNWARD (Sell)
    pattern_start_time: datetime       # Earliest swing point in pattern (can precede tap)
    confirmation_close_time: datetime  # Exact completed close time (MUST be >= tap_time)
```

### 3.2 Arbitration Tie-Breaker Protocol (`MTF-Analysis.pdf` §8)
When multiple activations hold pending status across timeframes:
1. **Primary Ranking**: Earliest `confirmation_close_time` wins.
2. **Simultaneous Timestamp Tie-Breaker 1 (Timeframe Precedence)**:
   $$\text{M1} \succ \text{M5} \succ \text{H1}$$
3. **Simultaneous Timestamp Tie-Breaker 2 (Role Precedence - Scoped to Same Source Timeframe)**:
   $$\text{TJL2 / A+} \succ \text{TJL1}$$
   *(Note: Role precedence applies strictly between competing levels from the same source timeframe; it does not rank across different timeframes).*
4. **Cancellation Trigger**: Selection of the winning entry triggers cancellation of all other pending activations across D1, H4, and H1.

### 3.3 Usage Ledger Protocol (`MTF-Analysis.pdf` §10)
```python
@dataclass(frozen=True)
class LevelUsageRecord:
    """Immutable ledger record tracking physical level consumption."""
    level_id: StableLevelId            # Unique physical level identifier
    used_status: bool                  # True if an entry was committed from this level
    usage_commit_time: datetime | None # Finalized commit timestamp
    winning_event_id: str | None       # Provenance link to winning confirmation event
```
- **RULE [One Trade Per Level]**: Each physical level supplies at most one trade in its lifetime. If `used_status is True`, the level is permanently ineligible for activation across all future sets, cycles, and weekly Monday carry-overs.
- **RULE [Touch Is Not Usage]**: Taps, repeated observations, and cancellations do NOT mark a level used. Only the accepted winning entry commits usage to the ledger.

---

## 4. Input & Evidence Contracts

All activation-acceptance fixtures adhere to these value object definitions:

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

### 4.2 Observed Price Event
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
    recorded_prints: tuple[float, ...] # Explicit discrete price prints observed in bar
```

### 4.3 Activation State Machine
```
[ INACTIVE_ELIGIBLE ]
        │
        ├─ Event: touch_observed (print p in [lower, upper] and t >= eligibility_available_time)
        ▼
[ PENDING_ACTIVATION ] ◄─── (Repeated touches logged as REPEATED_OBSERVATION)
        │
        ├─ Event: source_choch_invalidated ───► [ CANCELLED_SOURCE_CHOCH ] (Permanent)
        ├─ Event: source_set_replaced ────────► [ CANCELLED_SOURCE_REPLACEMENT ] (Permanent)
        ├─ Event: external_entry_committed ───► [ CANCELLED_EXTERNAL_ENTRY ] (Unused)
        │                                              │
        │                                              ├─ Scenario A: Inside at cancel -> leaves zone
        │                                              │  Scenario B: Already outside at cancel -> immediate arm
        │                                              ▼
        │                                       [ OUT_OF_ZONE_ARMED ]
        │                                              │
        │                                              ├─ Event: fresh_touch_observed
        │                                              ▼
        └─────────────────────────────────────── [ REARMED_PENDING ]
```

---

## 5. Acceptance Fixture Categories

The machine-readable acceptance suite in `tests/fixtures/activation_acceptance.json` contains 13 deterministic test categories covering all approved rules:

| Category ID | Scenario Name | Primary Authority | Key Assertions & Invariants |
|---|---|---|---|
| **`ACT_01`** | Known Availability First Touch | `MTF-Analysis.pdf` §5, §6 | Valid discrete print in $[L, U]$ at $t \ge t_{\text{avail}}$ transitions level to `PENDING_ACTIVATION`; maps confirmation timeframe. |
| **`ACT_01B`** | Both TJL1 & TJL2 Pending Independently | `MTF-Analysis.pdf` §8, Q&A 22 | Both members of active current set receive touches and hold pending activations concurrently. |
| **`ACT_01C`** | All Three Timeframe Mappings | `MTF-Analysis.pdf` §6 | Verifies D1 $\rightarrow$ H1, H4 $\rightarrow$ M5, and H1 $\rightarrow$ M1 confirmation mappings. |
| **`ACT_01D`** | t1 Retention Eligibility vs. Next Labels | `docs/requirements/tjl-acceptance.md` §5.2 | At t1, old current set remains eligible for tap; newly confirmed next labels in `all_labeled_zones` are ineligible. |
| **`ACT_02`** | Unknown Availability Blocks Activation | `docs/requirements/approved-clarifications.md` §4 | Null availability blocks activation evidence; level retains structural membership but cannot activate. |
| **`ACT_02B`** | Unknown Usage Evidence Blocks Activation | `MTF-Analysis.pdf` §10 | If level usage status is uncertain/unknown, activation is blocked (fail-closed). Explicitly unused required. |
| **`ACT_03`** | No Retroactive Wick Claim | `OPEN-04` | Candle interval strictly prior to $t_{\text{avail}}$ cannot be claimed; only subsequent touch activates. |
| **`ACT_03B`** | Intra-Candle Availability Ordering | `OPEN-04` | Availability falling intra-bar: known ordering activates; unknown intra-bar ordering blocks as `UNKNOWN_ORDER`. |
| **`ACT_04`** | Range Straddling Without Observed Print | `OPEN-06` | Bar straddling zone without discrete print in $[L, U]$ rejected as `NO_OBSERVED_TOUCH` (zero path interpolation). |
| **`ACT_04B`** | Inclusive Boundary Print & Line Level | `OPEN-06`, `MTF-Analysis.pdf` §4 | Exact boundary touch ($p = L$ or $p = U$) and zero-width line ($L = U$) successfully activate. |
| **`ACT_05`** | Repeated Observations No Reset | `MTF-Analysis.pdf` §5, Q&A 13 | Secondary/tertiary touches while pending do not reset `first_touch_time` or restart confirmation search. |
| **`ACT_06`** | Source CHOCH Cancellation | `MTF-Analysis.pdf` §9, `OPEN-03` | Source main CHOCH immediately cancels pending activation; status becomes `CANCELLED_SOURCE_CHOCH`. |
| **`ACT_07`** | Source t2 Replacement Cancellation | `MTF-Analysis.pdf` §9 | Pullback t2 replacement cancels SET_1 activation; new SET_2 requires independent touch. |
| **`ACT_07B`** | Persistent Member Survives Replacement | `MTF-Analysis.pdf` §4, §9 | Outgoing activation cancelled; same unused physical level survives into SET_2; no activation inheritance; fresh touch required. |
| **`ACT_08A`** | Already-Outside Cancellation Rearm | `OPEN-05` Path B | Price observed outside at cancellation: next later observed touch successfully rearms without extra departure. |
| **`ACT_08B`** | Lingering Inside Blocks Rearm | `OPEN-05` Path A | Price lingering inside zone after cancellation without confirmed outside observation blocks rearming. |
| **`ACT_09A`** | Coarse Timestamp Rearm After Winner Commit | `OPEN-12` | Later event at coarse timestamp $T$ rearms only *after* winning entry commit finalizes in event sequence. |
| **`ACT_09B`** | Pre-Commit Event / Recycled Evidence Rejected | `OPEN-12` | Event preceding winning commit or attempting to recycle competed tap/confirmation is rejected. |
| **`ACT_09C`** | Incomplete Batch / Unknown Coverage Blocks | `docs/requirements/approved-clarifications.md` §4 | Incomplete candle batch or uncertain feed coverage blocks activation transition (fail-closed). |
| **`ACT_10`** | Configuration Isolation & Replay | `OPEN-08`, `OPEN-09` | Independent engine runs isolated; idempotent replay reproduces identical activation sequence. |

---

## 6. Verification Boundaries & Non-Invention Policy

1. **Pure Requirements Baseline**: This document and its accompanying fixtures define the *criteria for acceptance* of any future activation engine.
2. **No Execution or Trading**: Activation does not place orders, verify margin, route requests, or compute lot sizes.
3. **No Missing Price-Path Invention**: If tick-level intra-bar price sequence is absent, candle wicks are evaluated strictly within declared timestamps; no speculative tick paths are inferred.
4. **Non-Settlement of Core Ambiguities**: Acceptance of these activation requirements does not settle upstream unresolved questions ($c_1 == p_2$ boundary or ISS multi-candle pullbacks).
