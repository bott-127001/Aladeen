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
│    - Exact price prints vs interval-bounded candle evidence            │
│    - Single configured price basis (Bid, Ask, Mid) [OPEN-06]           │
│    - Zero geometric path interpolation [OPEN-06]                       │
│    - Record availability != price occurrence time [OPEN-04]            │
│    - Prior-bar close cannot activate at that close boundary [OPEN-04]  │
│    - Blocked: UNKNOWN_ORDER, UNKNOWN_COVERAGE, NO_OBSERVED_TOUCH       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Emits TouchObservation
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Pending Activation Lifecycle (Activation Subsystem)                 │
│    - First touch -> PENDING_ACTIVATION (Starts confirmation search)    │
│    - Repeated touches -> REPEATED_OBSERVATION (No reset of search)     │
│    - Cancellation creates terminal record; retouch creates NEW record  │
│    - Rearming (OPEN-05):                                               │
│        * Already outside at cancellation -> next touch rearms          │
│        * Inside at cancellation -> later outside print -> fresh touch  │
│        * Lingering inside -> blocked (no rearming)                     │
│    - Event ordering at coarse timestamp T [OPEN-12]                    │
│        * Rearm occurs strictly after winning commit finalization       │
│        * Recycled tap/confirmation evidence strictly rejected          │
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

### 2.2 Observed Price Print Evidence & OHLC Temporal Semantics
- **RULE [OPEN-06: Physical Observation vs. Range Overlap]**:
  - A touch requires an actual observed price print $p$ on the single configured price basis (Bid, Ask, or Mid) such that:
    $$\text{lower\_edge} \le p \le \text{upper\_edge}$$
  - For an exact zero-width line level (`lower_edge == upper_edge`):
    $$p = \text{lower\_edge}$$
  - **Range Overlap Is Insufficient**: A candle whose high/low range straddles a zone ($\text{low} < \text{lower}$ and $\text{high} > \text{upper}$) without any recorded print in $[\text{lower}, \text{upper}]$ represents a candidate geometric intersection, NOT an observed touch. Discrete prices can jump or gap over a zone.
  - **Zero Geometric Path Interpolation**: No continuous price path between discrete ticks or candle bars may be assumed or interpolated.
- **RULE [Record Availability vs. Price Occurrence Time (OPEN-04)]**:
  1. *Half-Open Interval*: A candle's trade activity is strictly bounded within $[t_{\text{open}}, t_{\text{close}})$.
  2. *Record Availability Boundary*: The completed candle OHLC record becomes available at boundary $t_{\text{close}}$.
  3. *Close Price Proof Limitation*: A candle's close price records the final observed price *within that completed candle* $[t_{\text{open}}, t_{\text{close}})$. It DOES NOT prove a new price print occurred exactly at the boundary $t_{\text{close}}$.
  4. *No Preceding-Candle Close Activation*: A level becoming available at boundary $t_{\text{close}}$ CANNOT claim the preceding candle's close price as a new post-availability touch. That would be an unproven retroactive claim across the boundary (violating `OPEN-04`). An independent observed print at or after availability is strictly required.
  5. *Wick Extreme Timing*: A recorded High or Low extreme $p \in [\text{lower}, \text{upper}]$ proves price touched the zone at *some* instant during $[t_{\text{open}}, t_{\text{close}})$, but DOES NOT prove its exact intra-bar timestamp or sequence relative to intra-bar boundary events.
- **RULE [Intra-Candle Availability & Unknown Ordering (OPEN-04)]**:
  - If `eligibility_available_time` falls *inside* a candle interval $[t_{\text{open}}, t_{\text{close}})$:
    - If an independent print (or tick) has an established sequence/timestamp occurring at or after `eligibility_available_time`: valid touch.
    - If only the completed candle's OHLC is available (e.g. wick touches or close is inside zone) but intra-bar sequence relative to `eligibility_available_time` is unavailable, the transition is strictly blocked as `UNKNOWN_ORDER` (fail-closed).
- **ENGINEERING CONTRACT [Blocked Evidence Categories]**:
  - `NO_OBSERVED_TOUCH`: High/low range straddles zone but no discrete print inside.
  - `UNKNOWN_ORDER`: Intra-bar event sequence cannot be proven relative to availability, invalidation, or cancellation.
  - `UNKNOWN_COVERAGE`: Incomplete candle batches, missing bar gaps, or uncertain feed coverage.

### 2.3 Pending Activation Lifecycle & Identity
- **RULE [First Activation]**: The first valid observed touch transitions an unused, eligible level from `INACTIVE_ELIGIBLE` to `PENDING_ACTIVATION`, establishing `first_touch_time` and assigning the mapped confirmation timeframe:
  - D1 $\rightarrow$ H1
  - H4 $\rightarrow$ M5
  - H1 $\rightarrow$ M1
- **RULE [Repeated Observations Do Not Reset Search]**: Subsequent observed touches while an activation is already pending are recorded as `REPEATED_OBSERVATION` diagnostic events. They do NOT restart, reset, or delay the confirmation search (`MTF-Analysis.pdf` §5, Q&A 13).
- **RULE [Tap Is Not an Entry Signal]**: An activation does not place an order, calculate lot size, verify margin, or emit a trade entry.
- **ENGINEERING CONTRACT [Deterministic Activation Identity]**:
  - An activation record is a transient lifecycle object uniquely identified by:
    $$\text{activation\_id} = \text{f"ACT_{engine_id}_{level_id_tuple}_{set_id}_{seq_index}"}$$
  - Scoped strictly to its engine run, source timeframe, and set ID.

### 2.4 Cancellation and Precedence
- **RULE [Source Replacement Cancellation]**: When the source timeframe completes a pullback and qualifies a new `CurrentEligibleSet` (`SET_2`), pending activations on `SET_1` are immediately cancelled (`CANCELLED_SOURCE_REPLACEMENT`). The replacement set requires its own tap.
- **RULE [Source Main CHOCH Cancellation]**: When the source timeframe experiences main CHOCH, all pending activations in the old direction are cancelled immediately (`CANCELLED_SOURCE_CHOCH`), even before replacement TJLs form.
- **RULE [External Winning Entry Cancellation]**: When a trade is accepted from any active level across any timeframe, all other pending activations across D1, H4, and H1 are cancelled (`CANCELLED_EXTERNAL_ENTRY`).
- **RULE [OPEN-03: Shared-Close Invalidation Precedence]**: At a candle close where both source invalidation/replacement and a potential entry confirmation occur, source invalidation is evaluated **first**. An invalidated or replaced level cannot execute an entry at that timestamp.
- **ENGINEERING CONTRACT [Fail-Closed Scoping]**: In composite transitions, fail closed only for the specific transition branch lacking necessary evidence. A finalized source invalidation or replacement remains effective even if unrelated touch or confirmation evidence is unresolved elsewhere.

### 2.5 Rearming Semantics (OPEN-05)
An unused level whose activation was cancelled by an external winning entry may reactivate if it remains a member of the current eligible set:
- **RULE [OPEN-05 Path A: Cancelled While Inside Zone]**:
  - If the market price is observed inside the zone at the moment of cancellation:
  - An individual discrete print strictly outside the zone must be established ($p < \text{lower\_edge}$ or $p > \text{upper\_edge}$) with causal sequence occurring after the cancellation event.
  - A whole-bar-outside condition (`high < lower` or `low > upper`) is sufficient evidence, but an individual discrete outside print is the general criterion.
  - Only after an outside observation has been established does a subsequent fresh print inside the zone rearm the level.
- **RULE [OPEN-05 Path B: Cancelled While Already Observed Outside]**:
  - If the market price was already observed strictly outside the zone boundaries at the moment of cancellation:
  - The level is immediately armed for the next later observed touch without requiring another departure.
  - The next valid observed touch transitions the level to `REARMED_PENDING`.
- **RULE [Intra-Bar Departure and Retouch]**: If cancellation occurs intra-bar at sequence $s_1$, an outside print occurs at $s_2 > s_1$, and an inside print occurs at $s_3 > s_2$: valid rearming occurs *if and only if* explicit causal sequence is known. If sequence is unknown, rearming is strictly blocked as `UNKNOWN_ORDER`.
- **RULE [Lingering Inside Blocks Rearming]**: Remaining inside the zone after cancellation without an established outside observation strictly blocks rearming.
- **RULE [Unknown Outside State Blocks Rearming]**: If position relative to the zone cannot be proven, rearming is blocked (no speculative arming).
- **RULE [Retouch Creates New Linked Activation Record]**: Cancellation leaves the old activation record terminal. A subsequent qualifying retouch creates a brand new activation record with its own unique `activation_id`, linked to the prior record via `prior_activation_id`.
- **RULE [Fresh Confirmation Required]**: A reactivated level requires a fresh qualifying confirmation on or after the new tap candle; prior completed patterns cannot be reused.

### 2.6 Terminal Activation vs. Persistent Physical Level Identity
- **ENGINEERING CONTRACT [Transient Activation Object]**: An activation is a transient lifecycle state machine bound to `(set_id, role, first_touch_time)`. When cancelled, that specific activation record is terminal and cannot revive.
- **ENGINEERING CONTRACT [Persistent Physical Level Identity]**:
  - Physical levels are identified by immutable engineering formula:
    $$\text{StableLevelId} = (\text{symbol\_feed\_id}, \text{source\_timeframe}, \text{source\_open\_time}, \text{HIGH} \mid \text{LOW})$$
  - A physical level may survive into a replacement set (e.g. Case B/C persistent member) or reappear in a future structural epoch.
  - Surviving physical levels retain their identity and lifetime usage status.
  - **No Activation Inheritance**: A surviving unused level in a new set does NOT inherit pending activation from the replaced set. It requires its own independent touch under the new set to activate.
- **RULE [Usage State Preservation]**: Cancellation preserves known usage state from the usage ledger; it does NOT blindly assign `used_status = False` without ledger evidence.

### 2.7 Event Ordering at Coarse Timestamp T (OPEN-12)
- **RULE [OPEN-12 Sequencing]**: A later market event occurring at coarse timestamp $T$ may rearm an activation only *after* the winning entry commit has finalized in the event stream:
  $$\text{sequence\_ref}(\text{winning\_commit}) < \text{sequence\_ref}(\text{rearm\_event})$$
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
    sequence_ref: int                  # Authoritative causal sequence index
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
    usage_evidence_status: str         # "EXPLICITLY_UNUSED" | "UNCERTAIN_USAGE_LEDGER_UNVERIFIED"
```

### 4.2 Exact Price Print Evidence
```python
@dataclass(frozen=True)
class ExactPricePrint:
    """Discrete price print observed on the market data feed."""
    observation_id: str                # Unique immutable observation identifier
    price: float                       # Observed price
    price_basis: str                   # "BID" | "ASK" | "MID"
    timestamp: datetime                # Precise market timestamp
    sequence_ref: int                  # Authoritative causal sequence index
    consumed_by_event_id: str | None   # Tracking evidence reuse
```

### 4.3 Interval-Bounded Candle Evidence
```python
@dataclass(frozen=True)
class IntervalBoundedCandleEvidence:
    """Coarse candle bar evidence with half-open temporal bounds."""
    source_candle_id: str              # Unique candle identifier
    interval_open: datetime            # Bar open timestamp
    interval_close: datetime           # Completed record availability boundary
    field_name: str                    # "open" | "high" | "low" | "close"
    value: float                       # Recorded OHLC price value
    exact_time: datetime | None        # None if intra-bar timing is unknown
```

### 4.4 Activation State Machine
```
[ INACTIVE_ELIGIBLE ]
        │
        ├─ Event: touch_observed (exact print p in [lower, upper] and t >= eligibility_available_time)
        ▼
[ PENDING_ACTIVATION ] ◄─── (Repeated touches logged as REPEATED_OBSERVATION)
        │
        ├─ Event: source_choch_invalidated ───► [ CANCELLED_SOURCE_CHOCH ] (Terminal)
        ├─ Event: source_set_replaced ────────► [ CANCELLED_SOURCE_REPLACEMENT ] (Terminal)
        ├─ Event: external_entry_committed ───► [ CANCELLED_EXTERNAL_ENTRY ] (Terminal)
        │                                              │
        │                                              ├─ Path A: Inside at cancel -> later outside print
        │                                              │  Path B: Already outside at cancel -> immediate arm
        │                                              ▼
        │                                       [ OUT_OF_ZONE_ARMED ]
        │                                              │
        │                                              ├─ Event: fresh_touch_observed (Creates NEW activation)
        │                                              ▼
        └─────────────────────────────────────── [ REARMED_PENDING ]
```

---

## 5. Acceptance Fixture Categories

The machine-readable acceptance suite in `tests/fixtures/activation_acceptance.json` contains **20 deterministic test categories** covering all approved rules:

| Fixture ID | Category & Scenario Name | Primary Authority | Key Assertions & Invariants |
|---|---|---|---|
| **`act_01`** | Known Availability First Touch | `MTF-Analysis.pdf` §5, §6 | Valid discrete print in $[L, U]$ at $t \ge t_{\text{avail}}$ transitions level to `PENDING_ACTIVATION`; maps confirmation timeframe (H1 $\rightarrow$ M1). |
| **`act_01b`** | Both TJL1 & TJL2 Pending Independently | `MTF-Analysis.pdf` §8, Q&A 22 | Both members of active current set receive touches and hold pending activations concurrently. |
| **`act_01c`** | All Three Timeframe Mappings | `MTF-Analysis.pdf` §6 | Verifies D1 $\rightarrow$ H1, H4 $\rightarrow$ M5, and H1 $\rightarrow$ M1 confirmation mappings. |
| **`act_01d`** | t1 Retention Eligibility vs. Next Labels | `docs/requirements/tjl-acceptance.md` §5.2 | At t1, old current set remains eligible for tap; newly confirmed next labels in `all_labeled_zones` are ineligible. |
| **`act_02`** | Unknown Availability Blocks Activation | `docs/requirements/approved-clarifications.md` §4 | Null availability blocks activation evidence; level retains structural membership but cannot activate. |
| **`act_02b`** | Unknown Usage Evidence Blocks Activation | `MTF-Analysis.pdf` §10 | If level usage status is uncertain/unknown, activation is blocked (fail-closed). Explicitly unused required. |
| **`act_03`** | No Retroactive Wick Claim | `OPEN-04` | Candle interval strictly prior to $t_{\text{avail}}$ cannot be claimed; only subsequent touch activates. |
| **`act_03b`** | Intra-Candle Availability Ordering | `OPEN-04` | Availability falling intra-bar: known ordering activates; unknown intra-bar ordering blocks as `UNKNOWN_ORDER`. |
| **`act_03c`** | Available at Close Prior Close Cannot Activate | `OPEN-04`, `docs/requirements/activation-acceptance.md` §2.2 | Level available at candle close; prior candle's close price inside zone does NOT prove post-availability touch. |
| **`act_03d`** | Independent Print at Availability Activates | `OPEN-04`, `OPEN-06` | Independent discrete print at or after availability timestamp with established sequence order activates cleanly. |
| **`act_03e`** | Inside Candle Availability Unknown Sequence Blocks | `OPEN-04` | Availability inside candle; close price inside zone but occurrence ordering unknown -> `BLOCKED_UNKNOWN_ORDER`. |
| **`act_04`** | Range Straddling Without Observed Print | `OPEN-06` | Bar straddling zone without discrete print in $[L, U]$ rejected as `NO_OBSERVED_TOUCH` (zero path interpolation). |
| **`act_04b`** | Inclusive Boundary Print & Line Level | `OPEN-06`, `MTF-Analysis.pdf` §4 | Exact boundary touch ($p = L$ or $p = U$) and zero-width line ($L = U$) successfully activate. |
| **`act_05`** | Repeated Observations No Reset | `MTF-Analysis.pdf` §5, Q&A 13 | Secondary/tertiary touches while pending do not reset `first_touch_time` or restart confirmation search. |
| **`act_06`** | Source CHOCH Cancellation | `MTF-Analysis.pdf` §9, `OPEN-03` | Source main CHOCH immediately cancels pending activation; status becomes `CANCELLED_SOURCE_CHOCH`. |
| **`act_07`** | Source t2 Replacement Cancellation | `MTF-Analysis.pdf` §9 | Pullback t2 replacement cancels SET_1 activation; new SET_2 requires independent touch. |
| **`act_07b`** | Persistent Member Survives Replacement | `MTF-Analysis.pdf` §4, §9 | Outgoing activation cancelled; same unused physical level survives into SET_2; no activation inheritance; fresh touch required. |
| **`act_08a`** | Already-Outside Cancellation Rearm | `OPEN-05` Path B | Price observed outside at cancellation: next later observed touch successfully rearms without extra departure. |
| **`act_08b`** | Lingering Inside Blocks Rearm | `OPEN-05` Path A | Price lingering inside zone after cancellation without confirmed outside observation blocks rearming. |
| **`act_08c`** | Intra-Candle Outside Then Inside Known Sequence | `OPEN-05`, `OPEN-12` | Outside print ($p < L$) then inside print ($p \in [L, U]$) with proven sequence within same candle successfully rearms. |
| **`act_08d`** | Intra-Candle Outside & Inside Unknown Sequence | `OPEN-05`, `OPEN-12` | Both outside and inside prices exist within candle but relative sequence is unknown -> blocked (no speculative rearm). |
| **`act_09a`** | Coarse Timestamp Rearm After Winner Commit | `OPEN-12` | Later event at coarse timestamp $T$ rearms only *after* winning entry commit finalizes in event sequence. |
| **`act_09b`** | Pre-Commit Event / Recycled Evidence Rejected | `OPEN-12` | Event preceding winning commit or attempting to recycle competed tap/confirmation is rejected. |
| **`act_09c`** | Incomplete Batch / Unknown Coverage Blocks | `docs/requirements/approved-clarifications.md` §4 | Incomplete candle batch or uncertain feed coverage blocks activation transition (fail-closed). |
| **`act_09d`** | Two Reactivations at Same Coarse Timestamp | `OPEN-12`, `MTF-Analysis.pdf` §8 | Two distinct reactivations at timestamp $T$: distinct IDs, terminal prior records, zero recycled evidence. |
| **`act_10`** | Configuration Isolation & Replay | `OPEN-08`, `OPEN-09` | Independent engine runs isolated; idempotent replay reproduces identical activation sequence. |

---

## 6. Verification Boundaries & Non-Invention Policy

1. **Pure Requirements Baseline**: This document and its accompanying fixtures define the *criteria for acceptance* of any future activation engine.
2. **No Execution or Trading**: Activation does not place orders, verify margin, route requests, or compute lot sizes.
3. **No Missing Price-Path Invention**: If tick-level intra-bar price sequence is absent, candle wicks are evaluated strictly within declared timestamps; no speculative tick paths are inferred.
4. **Non-Settlement of Core Ambiguities**: Acceptance of these activation requirements does not settle upstream unresolved questions ($c_1 == p_2$ boundary or ISS multi-candle pullbacks).
