# Trade-Signal Business Logic & Acceptance Contract — Milestone 30

**Milestone**: Milestone 30 — Trade-Signal Business Logic Requirements and Acceptance Contract  
**Active Branch**: `requirements/trade-signal-acceptance`  
**Accepted Baseline Commit**: `0144ddb8150b4132a7b60d24698105d897514cb2` (Milestone 29 accepted)  
**Parent Documentation Commit**: `c159c6af10570739ded050e61be1b373fd98f084`  

> [!IMPORTANT]
> **Specification Authority & Provenance Boundary**:
> - **Primary Multi-Timeframe & Entry Confirmation Authority**: `docs/strategy/MTF-Analysis.pdf` (Version 1 — Consolidated rule record, 26 October 2026, 12:58 AM IST), transcribed in `docs/strategy/extracted/mtf-analysis.md`:
>   - *Section 1* (p. 1): Scope, Authority and Status (Disproven D1/H4/H1 trend alignment excluded; no agreement between timeframes required; stop loss/targets/position sizing are user responsibility).
>   - *Section 2* (p. 1): Analysis Versus Trade Finding (TJL is only source of marked trade-finding levels; CHOCH/ISS serve analysis on HTF and entry confirmation on assigned LTF after TJL activation; zones are not independent trade setups).
>   - *Section 3* (p. 1): Source Timeframes, Structure and Direction (D1, H4, H1 independently; TJL1 confirmed point 1, TJL2/A+ confirmed point 2; Bullish -> TJL1 Buy, TJL2 Buy; Bearish -> TJL1 Sell, TJL2 Sell; TJL1 follows source trend; same activation rule for TJL1 and TJL2).
>   - *Section 4* (pp. 1–2): Marked-Set Updates and Weekly Retention (Monday-to-Monday marking cycle; replacement on new 3-point set; retain levels if no new set on Monday; Monday alone does not delete, cancel, or reset usage; inherited zone-construction rules).
>   - *Section 5* (p. 2): Tap and Activation (Any wick touch activates; close inside not required; unused, eligible level only; first tap starts confirmation search; repeated taps do not reset search; tap is not an entry signal).
>   - *Section 6* (p. 2): Confirmation Mapping and Direction (D1 $\rightarrow$ H1, H4 $\rightarrow$ M5, H1 $\rightarrow$ M1; normal CHOCH or ISS; bullish requires fresh bullish normal CHOCH or bullish ISS; bearish requires fresh bearish normal CHOCH or bearish ISS; already-aligned trend is NOT sufficient; detection rules unchanged on assigned confirmation timeframes).
>   - *Section 7* (pp. 2–3): Confirmation Timing and Entry (Pattern may start before first tap, but must confirm on tap candle or afterward; confirmation completed before activation cannot be reused; tap candle may confirm; enter immediately at confirmation close without waiting for retest; confirming candle need not close inside zone; conceptual entry timing).
>   - *Section 8* (p. 3): Competing Activations and Tie-Breakers (First valid confirmation by close timestamp wins; simultaneous close chooses lower timeframe: M1 before M5 before H1; simultaneous same-source chooses TJL2 / A+; winning entry marks level used and cancels all other pending activations).
>   - *Section 9* (pp. 3–4): Cancellation and Reactivation (Replacement TJL set cancels old set; source main CHOCH immediately cancels old-direction activation; external entry cancels pending activations; price must leave zone and retouch to reactivate; used level cannot reactivate).
>   - *Section 10* (p. 4): One Trade Per Level (Each particular level supplies at most one trade; touch is not usage; entry commit is usage; repeated taps, cancellations, and Monday resets do not reset used status).
>   - *Section 11* (p. 4): User-Owned Risk and Management (Stop loss, targets, position sizing, trade management outside specification).
>   - *Section 12* (pp. 4–5): Complete Q&A Record (Questions 1–25).
> - **Approved Clarifications Authority**: [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (User approvals dated 4 November 2026, recorded in project artifact `aladin_topg_dashboard_e6a30e5e.plan.md`):
>   - `OPEN-03`: Invalidation Precedence at Shared Close (Source invalidation/replacement applied before evaluating entry eligibility).
>   - `OPEN-04`: Candle Timestamp Intervals & Wick Boundaries (Half-open intervals `[open_time, close_time)`; level cannot retroactively claim earlier candle wick; unknown ordering marks `UNKNOWN_ORDER`).
>   - `OPEN-05`: Rearming After Out-of-Zone Cancellation (When cancellation occurs while price is observed outside zone, next observed touch rearms).
>   - `OPEN-06`: Single Price Basis & Physical Observation (Configured Bid/Ask/Mid; actual observed print inside `[lower, upper]`; zero path interpolation).
>   - `OPEN-07`: Multiple Confirmation Evidence Consolidation (When a single entry setup possesses both CHOCH and ISS confirmation evidence, record both confirmation identifiers on that single entry record; do NOT generate duplicate signals).
>   - `OPEN-08`: Independent Engine Configuration & Manual Start Validation (Isolated runs; no silent start inheritance; clean calculation runs).
>   - `OPEN-09`: Origin, Evidence Status & Immutable Signals (Immutable published records; versioned replay from prior valid dependency).
>   - `OPEN-10`: Native MT5 Boundaries & Persisted Source Calendar (Native MT5 bar times; weekly boundary within broker source calendar).
>   - `OPEN-11`: Chronological Signal Listing Without Position Gating (List every conceptual trade signal chronologically as it occurs, including subsequent opposite-side signals; analysis engine must not filter, suppress, or gate signals based on hypothetical open positions).
>   - `OPEN-12`: Event Ordering at Coarse Timestamp T (Later event rearms only after winning entry commit finalizes).
> - **Verification Provenance & Authority Distinctions**:
>   - Strategy text cited above is verified from the markdown transcription `docs/strategy/extracted/mtf-analysis.md` and repository documentation.
>   - Transcribed PDF page numbers are recorded as preserved from the transcription metadata; direct underlying PDF page validation remains uninspected in this phase.
>   - Operational engineering proposals (e.g. same-candle consolidation boundary, transaction commit boundary) are explicitly labeled as implementation contracts requiring acceptance, distinguished from verbatim source strategy rules.
> - **Strict Safety & Scope Boundary**: Requirements reconciliation, fixture design, and acceptance contract specification only. Strictly **zero runtime signal engine implementation, zero UI order execution, zero MT5 live trading calls, zero live account modification, zero automated trading, and zero merging to `main`**.

---

## 1. Domain Terminology & Entity Lifecycle

The trade-signal business logic defines five distinct conceptual entities across the decision pipeline:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. Source Structural Level (TJL Engine: D1, H4, H1)                                    │
│    - Identified by physical StableLevelId:                                             │
│        (symbol_feed_id, source_timeframe, source_open_time, side)                      │
│    - Status: INACTIVE_ELIGIBLE, LABELS_ONLY, or USED (within calculation namespace)    │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Price Touch Print
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. Pending Activation (Activation Engine)                                              │
│    - PENDING_ACTIVATION (initial touch) or REARMED_PENDING (fresh touch after cancel)  │
│    - Maps designated confirmation timeframe (D1->H1, H4->M5, H1->M1)                   │
│    - Non-resetting across subsequent touches within the same activation generation     │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Qualifying Pattern Confirms On/After Tap
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. Confirmed Setup Candidate (Signal Engine Evaluation)                                │
│    - Lower-timeframe directional pattern (Bullish/Bearish Normal CHOCH or ISS)        │
│    - Valid provenance: completed pattern, resolved dependencies, unbroken causality   │
│    - Invalidation pre-checks: source replacement, source main CHOCH                    │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Arbitration / Tie-Breakers (upon complete due evidence)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 4. Selected Winning Entry & Published Signal (Dashboard Presentation)                  │
│    - Earliest close timestamp wins; ties broken by lower TF, then TJL2 (A+)            │
│    - ATOMIC CONCEPTUAL COMMIT:                                                         │
│        * Selects winning candidate                                                     │
│        * Emits immutable PublishedTradeSignal: BUY or SELL                             │
│        * Consumes physical level: marks StableLevelId as USED in scoped ledger         │
│        * Cancels all other pending activations across D1, H4, H1 in domain session     │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ STRICT SAFETY BOUNDARY (OUT OF SCOPE)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 5. Executed Trade (Live Broker Order Placement)                                        │
│    - [STRICTLY FORBIDDEN / 0% IMPLEMENTED / NON-PRODUCTION BOUNDARY]                   │
│    - Stop-loss, take-profit, position sizing, order routing, fills                     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Distinction of Events & Safety Invariant:
- **Signal Publication**: The deterministic generation and display of a conceptual trade signal on the read-only dashboard.
- **Entry Selection**: The arbitration decision where the earliest qualifying candidate wins and other pending activations are cancelled.
- **Usage Consumption**: The permanent state transition where the winning physical `StableLevelId` is marked `USED` in the scoped calculation usage ledger.
- **Executed Trade**: Broker order placement and execution. **This does NOT exist in the Aladeen dashboard**. Published signals explicitly carry `is_broker_execution: false` and `signal_type: "CONCEPTUAL_ANALYSIS_SIGNAL"`.

---

## 2. Nine-Stage Decision Chain Specification

### Stage 1: Eligible Source Context
- **Timeframes**: D1, H4, and H1 source timeframes operate independently (`MTF-Analysis.pdf` §3).
- **Structure & Direction**:
  - Bullish Structure $\rightarrow$ Both TJL1 and TJL2 qualify for **BUY** trade signals (`MTF-Analysis.pdf` §3).
  - Bearish Structure $\rightarrow$ Both TJL1 and TJL2 qualify for **SELL** trade signals (`MTF-Analysis.pdf` §3).
  - TJL1 strictly follows the source structure trend direction. It does not trade in the opposite direction merely because its source point is a high or low (`MTF-Analysis.pdf` §3, Q&A 20).
- **Physical Level Identity**:
  - Identified authoritatively by the 4-tuple:  
    `StableLevelId(symbol_feed_id, source_timeframe, source_open_time, side)`.
- **Set Membership**: Only zones belonging to the active `CurrentEligibleSet` (`SET_1` or `SET_2`) are eligible. At continuation `t1`, the current set remains eligible; labels-only zones awaiting set replacement are ineligible (`docs/requirements/tjl-acceptance.md` §5.2).

### Stage 2: Activation Prerequisite
- **Eligible Activation States**: Both `PENDING_ACTIVATION` (initial valid touch) and `REARMED_PENDING` (fresh touch following departure after cancellation) permit confirmation evaluation.
- **Physical Touch**: Any wick touch (high/low price print inside or on inclusive zone boundaries `[lower_edge, upper_edge]`) is sufficient; a close inside is not required (`MTF-Analysis.pdf` §5, Q&A 11).
- **Eligibility Check**: Only an unused level (`used_status == false` in the active calculation namespace) can activate. A previously used level is permanently dead (`MTF-Analysis.pdf` §5, §10).
- **First Tap Reference**: The first tap timestamp establishes the lower bound for confirmation search. Repeated touches during pending activation do not restart or reset the search (`MTF-Analysis.pdf` §5, Q&A 13).

### Stage 3: Confirmation Requirements, Provenance & Causality
- **Mapping Table** (`MTF-Analysis.pdf` §6):
  | Source Timeframe | Assigned Confirmation Timeframe | Accepted Confirmation Patterns |
  |---|---|---|
  | **D1** | **H1** | Authoritative Normal CHOCH or Authoritative Confirmed ISS |
  | **H4** | **M5** | Authoritative Normal CHOCH or Authoritative Confirmed ISS |
  | **H1** | **M1** | Authoritative Normal CHOCH or Authoritative Confirmed ISS |
- **Directional Concordance**:
  - Intended BUY signal $\rightarrow$ Requires **Bullish Normal CHOCH** or **Bullish Confirmed ISS** (`MTF-Analysis.pdf` §6, Q&A 4).
  - Intended SELL signal $\rightarrow$ Requires **Bearish Normal CHOCH** or **Bearish Confirmed ISS** (`MTF-Analysis.pdf` §6, Q&A 4).
  - An opposite-direction confirmation is strictly rejected (`REJECTED_DIRECTION_MISMATCH`).
- **Authoritative Confirmation Provenance (Addressing Review Directive 1 & 6)**:
  - Merely being an event emitted by an engine module is insufficient. A valid confirmation requires:
    1. Valid structural provenance: derived from real underlying candle sequence meeting all strategy definitions (`Choch.pdf`, `ISS.pdf`, `Market Structure Marking.docx`).
    2. Valid completion status: `is_completed: true` on the confirmation candle close.
    3. Resolved dependencies: zero unresolved structural ambiguity in source or confirmation calculations.
  - **Isolated tracking records** (`ISOLATED_TRACKING_ONLY`) or synthetic completion evidence do NOT constitute entry confirmation (`REJECTED_ISOLATED_TRACKING_NOT_CONFIRMATION`).
  - **Unresolved detection paths** (including multi-candle pullback ambiguity where strategy rules remain unreconciled) fail closed as `BLOCKED_UNRESOLVED_CONFIRMATION_GAP` and emit no trade signals. No candle-count heuristic is invented.
- **Fresh Transition Required**:
  - An already-aligned trend is NOT sufficient; a fresh CHOCH or ISS transition event is mandatory (`MTF-Analysis.pdf` §6, Q&A 19).
- **Same-Candle Causality & Evidence Contract (Addressing Review Directive 3)**:
  - `MTF-Analysis.pdf` §7 (Q&A 12) provides that the tap candle may also confirm entry if it confirms a valid pattern.
  - Three distinct causal timing cases apply:
    * **Case A (Exact Observed Print Preceding Close)**: Exact observed touch timestamp is strictly prior to confirmation close timestamp ($t_{tap} < t_{close}$) $\rightarrow$ Eligible timing.
    * **Case B (Shared Coarse Timestamp with Authoritative Ordering Evidence)**: Tap and confirmation share a coarse candle timestamp, but monotonic sequence indexing proves touch preceded pattern completion (e.g. sequence index $seq_{tap} < seq_{conf}$) $\rightarrow$ Eligible timing.
    * **Case C (OHLC Overlap without Sequence Evidence)**: Tap and confirmation share a coarse bar, but the feed provides only OHLC bounds without intra-bar sequence ordering $\rightarrow$ Fail closed as `UNKNOWN_ORDER`. No signal emitted.
  - A confirmation completed strictly before activation cannot be reused (`PRE_ACTIVATION_CONFIRMATION_REJECTED`).
  - Do NOT wait for a retest of zones created by CHOCH or ISS (`MTF-Analysis.pdf` §7, Q&A 6).
- **Location Independence**:
  - The confirming candle does NOT need to close inside the tapped source TJL zone; confirmation remains valid after price has moved away, provided activation has not been cancelled (`MTF-Analysis.pdf` §7, Q&A 5).

### Stage 4: Candidate Invalidation & Cancellation Precedence
- **Precedence at Shared Close (`OPEN-03`)**:
  - At a shared candle close timestamp where both an invalidation/replacement and a potential confirmation occur, source invalidation is evaluated **before** confirming entry eligibility.
- **Cancellation Triggers** (`MTF-Analysis.pdf` §9):
  1. *Source TJL Replacement*: Formation of a replacement TJL set on the same source timeframe cancels activation of the replaced level (`MTF-Analysis.pdf` §9, Q&A 10).
  2. *Source Main CHOCH*: A Main CHOCH on the activated level's source timeframe immediately cancels old-direction activation (`MTF-Analysis.pdf` §9, Q&A 24).
  3. *Cross-Timeframe Non-Interference*: A new TJL update on another source timeframe does NOT cancel pending activations on other timeframes (`MTF-Analysis.pdf` §9, Q&A 10).
  4. *Winning Entry on Any Timeframe*: A winning entry selection immediately cancels all other pending activations across D1, H4, and H1 within the active domain session (`MTF-Analysis.pdf` §8, §9, Q&A 16).

### Stage 5: Declared Arbitration Domain, Completeness & Tie-Breaking (Addressing Review Directives 2 & 4)
- **Three-Tier Calculation Namespace Separation (Addressing Review Directive 1)**:
  To prevent cross-run pollution and clarify replay semantics, three distinct identities are maintained:
  1. **Strategy / Configuration Identity**: The strategy parameters tuple:  
     `(server, symbol, price_basis, timeframe_configuration, manual_start_time, rule_version)`.
  2. **Calculation Namespace / Domain Session**: The concrete runtime execution instance:  
     `DomainSession = (calculation_identity, session_id, sequence_domain_run_id)`.  
     Usage consumption, level states, and pending activations are strictly scoped to this `DomainSession`. Independent research sessions or different manual start times do NOT cross-consume levels.
  3. **Replay Version**: A versioned calculation run (`revision_id` / `run_version`). A fresh recalculation from historical event sequence rebuilds its own clean usage ledger from scratch; it does NOT mutate prior versioned ledgers or leak consumption.
- **Evidence Completeness Defined by Due Events (Addressing Review Directive 2)**:
  - Completeness at timestamp $T$ does NOT require every higher timeframe to close simultaneously. An ordinary H1, H4, or D1 bar normally forming across $T$ is NOT missing evidence.
  - Completeness requires: **All events, bars, and invalidations due at or before $T$ across all participating timelines in the declared domain are accounted for**.
  - An M1 confirmation at 08:05:00 is fully complete and eligible to arbitrate, even while H1 `[08:00, 09:00)` is forming, provided that all M1, M5, H1, H4, and D1 data *due* at or before 08:05:00 has been received.
  - If a due event is missing (e.g. feed gap, unclosed bar due at $T$, or unreceived source replacement), arbitration is blocked fail-closed (`BLOCKED_INCOMPLETE_EVIDENCE_COVERAGE`).
- **Order-Independent Deterministic Tie-Breaking**:
  - Competing candidates evaluated at timestamp $T$ are deterministically sorted by:
    1. **Primary**: Earliest completed confirmation `close_timestamp` (ascending) (`MTF-Analysis.pdf` §8, Q&A 15).
    2. **Secondary (Simultaneous Timestamps)**: Lower confirmation timeframe (`M1` before `M5` before `H1`) (`MTF-Analysis.pdf` §8, Q&A 18).
    3. **Tertiary (Simultaneous Same-Source TJL1 vs TJL2)**: Prefer **TJL2 / A+** over TJL1 (`MTF-Analysis.pdf` §8, Q&A 22).
  - The winner is selected strictly by this hierarchy. Event delivery arrival order has zero strategy priority.

### Stage 6: Atomic Conceptual Commit, Finalization & Late Evidence (Addressing Review Directives 4 & 5)
- **Atomic Conceptual Commit Transaction**:
  - The winning entry commit is an atomic, idempotent operation within the active `DomainSession`:
    1. Designates the winning candidate setup.
    2. Consumes the winning physical level: permanently marks `StableLevelId` as `USED` in the scoped usage ledger.
    3. Records and publishes the immutable `PublishedTradeSignal`.
    4. Routes cancellation events across all other pending activations (`PENDING_ACTIVATION` and `REARMED_PENDING`) across D1, H4, and H1 within the active domain session.
  - Failure at any step rolls back completely (zero partial commits).
- **Finalization & Idempotent Retry**:
  - Retrying an identical commit (same `commit_id` and content) succeeds idempotently and returns the existing commit record.
  - Retrying a commit with conflicting content for the same `commit_id` is strictly rejected (`COMMIT_CONFLICT_REJECTED`).
- **Late Evidence Policy**:
  - *Candidate arriving before batch finalization*: Evaluated into the pending batch before commit.
  - *Confirmation arriving after batch was finalized*: The winning commit at $T$ is already finalized; the late confirmation cannot retrospectively mutate the winner or cancel it. It is logged as diagnostic (`LATE_CONFIRMATION_IGNORED`).
  - *Correction of historical feed data*: Published signals are strictly immutable (`OPEN-09`). Corrections trigger a versioned replay run with a new `run_version`, never in-place signal mutation.
- **Confirmation Consolidation Engineering Policy (Addressing Review Directive 5)**:
  - *Operational Policy*: In accordance with `OPEN-07`, when a single entry setup possesses both CHOCH and ISS confirmation evidence, both confirmation identifiers are recorded on a single signal record.
  - To prevent delaying valid entries while preserving immutability, the operational grouping policy specifies that two confirmation events consolidate into a single signal when they share the same physical level, same activation generation, same confirmation timeframe, and complete on the **exact same confirmation candle close**.
  - A second confirmation completing on a later candle does NOT delay entry and does NOT retrospectively mutate the published signal (`OPEN-09`).

### Stage 7: Scoped Usage Accounting & Namespace Isolation
- **One Trade Per Level Contract (`MTF-Analysis.pdf` §10)**:
  - Each physical level (`StableLevelId`) can supply **at most one trade** in its entire lifetime (`MTF-Analysis.pdf` §10).
  - Taps, cancellations, repeated touches, and weekly roll-overs do NOT consume a level; only an accepted atomic conceptual commit consumes it (`MTF-Analysis.pdf` §10).
  - A used level is permanently dead and can never reactivate or produce another signal, even if price touches it again or it is retained into subsequent weeks (`MTF-Analysis.pdf` §4, §10).
- **Session Namespace Isolation**:
  - Usage ledger is strictly scoped to `DomainSession`. Independent sessions or distinct start candles maintain isolated ledgers and do NOT cross-consume levels (`OPEN-08`).

### Stage 8: Repeat Signals & Rearming Semantics
- **Rearming Unused Cancelled Levels (`MTF-Analysis.pdf` §9, `OPEN-05`)**:
  - An unused level cancelled because another timeframe's entry won may reactivate if it is still a member of the current eligible set (`MTF-Analysis.pdf` §9, Q&A 17).
  - **Path B (Already Outside)**: If price was already outside the zone boundaries at the moment of cancellation, the very next observed price touch transitions the level to `REARMED_PENDING` (`OPEN-05`).
  - **Path A (Inside Zone at Cancellation)**: If price was inside the zone at cancellation, price must first leave the zone; remaining or lingering inside does NOT count (`MTF-Analysis.pdf` §9, Q&A 25). The next touch after departure transitions the level to `REARMED_PENDING`.
- **Fresh Confirmation Required**:
  - A rearmed level requires a fresh qualifying confirmation on its new tap candle or afterward. Prior confirmations cannot be recycled (`MTF-Analysis.pdf` §9).
- **Coarse Timestamp T Event Ordering (`OPEN-12`)**:
  - At a shared coarse timestamp T, rearming of a cancelled level can only occur strictly after the winning entry commit has finalized (`OPEN-12`). Recycled tap evidence is strictly rejected.

### Stage 9: Latest/History Presentation & Deterministic Replay
- **Signal History Retention**:
  - All published signals are retained in an immutable chronological ledger.
  - The dashboard displays the latest active signal status alongside historical signals.
- **Deterministic Replay (`OPEN-09`)**:
  - Replaying market data from the configured start candle must produce identical signals with identical timestamps, identifiers, and sequences.

---

## 3. Preserved Strategy Gaps & Fail-Closed Handling

The following unresolved strategy questions are handled with explicit fail-closed logic:

| Unresolved Issue | Affected Scope | Fail-Closed Policy | Minimal Decision for Samarth |
|---|---|---|---|
| **CHOCH $c_1 == p_2$ Close Equality** | Source MSM/CHOCH engine state freezing | If source structure freezes in unresolved ambiguity, signal evaluation for that source timeframe is immediately frozen (`BLOCKED_SOURCE_UNRESOLVED`). No signal emitted. | Formally reconcile whether $c_1 == p_2$ constitutes an upward continuation, downward reversal, or containment freeze. |
| **ISS Multi-Candle Pullback Qualification** | Lower-timeframe ISS confirmation setups | Candidate ISS confirmations involving multi-candle pullbacks where strategy rules remain unclarified fail closed as `BLOCKED_UNRESOLVED_CONFIRMATION_GAP`. No signal emitted. | Formally reconcile whether multi-candle pullback ISS patterns qualify as valid entry confirmation. |
| **Intra-Candle Ordering Limitation (`OPEN-04`)** | Coarse bars where tap and confirmation occur on the same candle without sub-bar tick ordering | If sub-bar order cannot be established with certainty from the data feed, mark `UNKNOWN_ORDER` and suppress signal publication. Recorded as a feed/data limitation. | Acknowledge that coarse data feeds without sub-bar timestamps suppress same-candle tap/confirmation signals fail-closed. |

---

## 4. Integration Gap Assessment

### 4.1 Currently Available Engine Outputs (Accepted Baselines):
1. **MSM Engine (`MSMEngine`)**: Confirmed swing highs/lows, trend status, and validated candle sequence.
2. **CHOCH Detector (`ChochDetector`)**: Directional CHOCH events, continuation resets, and unresolved freeze flags.
3. **ISS Engine (`ISSEngine`)**: 5-point structural shifts, isolated tracking records, and terminal states.
4. **TJL Coordinator (`TJLCoordinator`)**: Current eligible sets (`tjl1_zone`, `tjl2_zone`), t1 retention, and t2 replacement records.
5. **Activation Engine (`ActivationSessionCoordinator`)**: Ingestion of physical price prints, `PENDING_ACTIVATION` and `REARMED_PENDING` state tracking, and rearming state machines.

### 4.2 Missing Components Required for Signal Generation:
1. **Multi-Timeframe Confirmation Monitor**:
   - Subsystem to ingest lower-timeframe candle streams (H1 for D1, M5 for H4, M1 for H1) and execute real-time CHOCH/ISS pattern matching scoped to pending/rearmed activations.
2. **Candidate Arbitration Engine**:
   - Cross-timeframe comparator implementing the declared arbitration domain, complete due-evidence verification, and the 3-level tie-breaking hierarchy (earliest close $\rightarrow$ lower TF $\rightarrow$ TJL2/A+).
3. **Usage Ledger Subsystem**:
   - Thread-safe, scoped ledger recording `StableLevelId` consumption within `DomainSession` namespace.
4. **Dashboard Signal Presentation Components**:
   - Visual signal markers on Plotly candlestick charts (arrows/banners) and chronological Signal Inspection Table in Dash layout.

### 4.3 Proposed First Implementable Subset (Milestone 31):
- Implement the **Multi-Timeframe Confirmation Monitor** (offline LTF CHOCH/ISS pattern detection strictly scoped to existing `PENDING_ACTIVATION` and `REARMED_PENDING` states emitted by `ActivationSessionCoordinator`).
- Emits candidate confirmation events without performing premature arbitration or state mutation. Candidate arbitration and scoped usage ledger follow in Milestone 32.
