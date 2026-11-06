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
> - **Verification Provenance Disclosure**:
>   - Strategy text cited above is verified from the markdown transcription `docs/strategy/extracted/mtf-analysis.md` and repo documentation. Direct inspection of original PDF page numbers is recorded as transcribed; no citations are invented.
> - **Strict Safety & Scope Boundary**: Requirements reconciliation, fixture design, and acceptance contract specification only. Strictly **zero runtime signal engine implementation, zero UI order execution, zero MT5 live trading calls, zero live account modification, zero automated trading, and zero merging to `main`**.

---

## 1. Domain Terminology & Entity Lifecycle

The trade-signal business logic defines five distinct conceptual entities across the decision pipeline:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. Source Structural Level (TJL Engine: D1, H4, H1)                                    │
│    - Identified by physical StableLevelId:                                             │
│        (symbol_feed_id, source_timeframe, source_open_time, side)                      │
│    - Status: INACTIVE_ELIGIBLE, LABELS_ONLY, or USED                                   │
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
│    - Evaluated at confirmation candle close time within complete batch coverage        │
│    - Invalidation pre-checks: source replacement, source main CHOCH                    │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Arbitration / Tie-Breakers (if competing)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 4. Selected Winning Entry & Published Signal (Dashboard Presentation)                  │
│    - Earliest close timestamp wins; ties broken by lower TF, then TJL2 (A+)            │
│    - ATOMIC CONCEPTUAL COMMIT:                                                         │
│        * Selects winning candidate                                                     │
│        * Emits immutable PublishedTradeSignal: BUY or SELL                             │
│        * Consumes physical level: marks StableLevelId as USED in scoped ledger         │
│        * Cancels all other pending activations across D1, H4, H1 in domain             │
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
- **Usage Consumption**: The permanent state transition where the winning physical `StableLevelId` is marked `USED` in the scoped usage ledger.
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
  - Identified authoritatively by `StableLevelId(symbol_feed_id, source_timeframe, source_open_time, side)`.
- **Set Membership**: Only zones belonging to the active `CurrentEligibleSet` (`SET_1` or `SET_2`) are eligible. At continuation `t1`, the current set remains eligible; labels-only zones awaiting set replacement are ineligible (`docs/requirements/tjl-acceptance.md` §5.2).

### Stage 2: Activation Prerequisite
- **Eligible Activation States**: Both `PENDING_ACTIVATION` (initial valid touch) and `REARMED_PENDING` (fresh touch following departure after cancellation) permit confirmation evaluation.
- **Physical Touch**: Any wick touch (high/low price print inside or on inclusive zone boundaries `[lower_edge, upper_edge]`) is sufficient; a close inside is not required (`MTF-Analysis.pdf` §5, Q&A 11).
- **Eligibility Check**: Only an unused level (`used_status == false`) can activate. A previously used level is permanently dead (`MTF-Analysis.pdf` §5, §10).
- **First Tap Reference**: The first tap timestamp establishes the lower bound for confirmation search. Repeated touches during pending activation do not restart or reset the search (`MTF-Analysis.pdf` §5, Q&A 13).

### Stage 3: Confirmation Requirements & Mapping
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
- **Authoritative Pattern Definitions (Correction for Directive 1)**:
  - An authoritative confirmed directional ISS event produced by `ISSEngine` (5-point structural shift with valid completion close) qualifies as confirmation.
  - Isolated tracking records (`ISOLATED_TRACKING_ONLY`) or synthetic completion evidence do NOT constitute entry confirmation (`REJECTED_ISOLATED_TRACKING_NOT_CONFIRMATION`).
  - Unresolved detection paths (e.g. multi-candle pullback ambiguity where strategy rules remain unreconciled) are marked `BLOCKED_UNRESOLVED_CONFIRMATION_GAP` and emit no trade signals. No pattern selection by candle count is invented.
- **Fresh Transition Required**:
  - An already-aligned trend is NOT sufficient; a fresh CHOCH or ISS transition event is mandatory (`MTF-Analysis.pdf` §6, Q&A 19).
- **Causal Timing** (`MTF-Analysis.pdf` §7):
  - A confirmation pattern may start forming before the first tap, but its completion close must occur **on the tap candle or afterward** (`MTF-Analysis.pdf` §7, Q&A 14).
  - A confirmation completed strictly before activation cannot be reused (`PRE_ACTIVATION_CONFIRMATION_REJECTED`).
  - If the tap candle also confirms the pattern, entry occurs at that candle's close (`MTF-Analysis.pdf` §7, Q&A 12).
  - Otherwise, entry occurs immediately at the subsequent qualifying confirmation close (`MTF-Analysis.pdf` §7, Q&A 6).
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
  4. *Winning Entry on Any Timeframe*: A winning entry selection immediately cancels all other pending activations across D1, H4, and H1 (`MTF-Analysis.pdf` §8, §9, Q&A 16).

### Stage 5: Declared Arbitration Domain & Tie-Breaking Hierarchy (Correction for Directive 3)
- **Declared Arbitration Domain**:
  - Arbitration operates strictly within a declared calculation identity:  
    `CalculationIdentity = (server, symbol, price_basis, timeframe_configuration, manual_start_time, rule_version)`.
- **Completeness & Coverage Boundary**:
  - Before committing a winner at timestamp $T$, the evaluator must verify that all participating confirmation and source timelines have complete, closed coverage through timestamp $T$.
  - If any participating timeframe's feed has missing bars or an unclosed bar at $T$, arbitration is blocked fail-closed (`BLOCKED_INCOMPLETE_EVIDENCE_COVERAGE`). Candidate arrival order must never prematurely commit a winner.
- **Order-Independent Deterministic Tie-Breaking**:
  - Candidates evaluated in a batch are deterministically sorted by:
    1. **Primary**: Earliest completed confirmation `close_timestamp` (ascending) (`MTF-Analysis.pdf` §8, Q&A 15).
    2. **Secondary (Simultaneous Timestamps)**: Lower confirmation timeframe (`M1` before `M5` before `H1`) (`MTF-Analysis.pdf` §8, Q&A 18).
    3. **Tertiary (Simultaneous Same-Source TJL1 vs TJL2)**: Prefer **TJL2 / A+** over TJL1 (`MTF-Analysis.pdf` §8, Q&A 22).
  - The winner is selected strictly by this hierarchy, regardless of candidate event delivery order.

### Stage 6: Atomic Conceptual Commit & Publication (Correction for Directive 4 & 6)
- **Atomic Conceptual Commit Transaction**:
  - The conceptual commit is an atomic, idempotent operation within the declared arbitration domain that simultaneously:
    1. Designates the winning candidate setup.
    2. Consumes the winning physical level: permanently marks `StableLevelId` as `USED` in the scoped usage ledger.
    3. Emits and records the immutable `PublishedTradeSignal`.
    4. Routes cancellation events across all other pending activations (`PENDING_ACTIVATION` and `REARMED_PENDING`) across D1, H4, and H1 within the active domain session.
  - Failure at any step leaves zero side effects (no unconsumed signal, no orphan consumption, and no partial cancellations).
- **Confirmation Consolidation Semantics (`OPEN-07`)**:
  - Two confirmation events consolidate into a single signal if and only if they share:
    * The same tapped physical level (`StableLevelId`),
    * The same activation generation,
    * The same confirmation timeframe, and
    * Complete on the **exact same confirmation candle close timestamp**.
  - The setup is finalized at that close timestamp.
  - If an additional confirmation pattern completes on a later candle after a valid signal was already published at an earlier close, it does NOT delay entry and does NOT retrospectively mutate the already-published signal. Earliest valid confirmation immediately publishes the immutable signal.
- **Published Signal Record**:
  - Required Fields: `signal_id`, `timestamp_utc`, `symbol`, `signal_side` (BUY/SELL), `source_timeframe`, `source_level_role` (TJL1/TJL2), `stable_level_id`, `confirmation_timeframe`, `confirmation_pattern_types` (list), `confirmation_event_ids` (list), `entry_price` (confirmation close price), `calculation_identity`, `is_broker_execution: false`, `signal_type: "CONCEPTUAL_ANALYSIS_SIGNAL"`.
- **Chronological Listing Without Position Gating (`OPEN-11`)**:
  - Signals are published chronologically as they occur, including subsequent opposite-side signals. The engine does NOT filter or suppress signals based on hypothetical open positions (`OPEN-11`).

### Stage 7: Scoped Usage Accounting & Namespace Isolation (Correction for Directive 5)
- **One Trade Per Level Contract (`MTF-Analysis.pdf` §10)**:
  - Each physical level (`StableLevelId`) can supply **at most one trade** in its entire lifetime (`MTF-Analysis.pdf` §10).
  - Taps, cancellations, repeated touches, and weekly roll-overs do NOT consume a level; only an accepted atomic conceptual commit consumes it (`MTF-Analysis.pdf` §10).
  - A used level is permanently dead and can never reactivate or produce another signal, even if price touches it again or it is retained into subsequent weeks (`MTF-Analysis.pdf` §4, §10).
- **Scoped Ledger Namespace**:
  - The usage ledger is strictly scoped to the `CalculationIdentity` namespace:  
    `(server, symbol, price_basis, timeframe_configuration, manual_start_time, rule_version)`.
  - Independent calculation runs, different manual starting candles, or distinct sessions do NOT cross-consume levels (`OPEN-08`).

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
| **ISS Multi-Candle Pullback Qualification** | Lower-timeframe ISS confirmation setups | Candidate ISS confirmations on H1, M5, or M1 involving multi-candle pullbacks are marked `BLOCKED_UNRESOLVED_CONFIRMATION_GAP`. No signal emitted. Only authoritative confirmed ISS events without ambiguous pullback paths qualify. | Formally reconcile multi-candle pullback rules for ISS confirmation. |
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
   - Cross-timeframe comparator implementing the declared arbitration domain, complete coverage verification, and the 3-level tie-breaking hierarchy (earliest close $\rightarrow$ lower TF $\rightarrow$ TJL2/A+).
3. **Usage Ledger Subsystem**:
   - Thread-safe, scoped ledger recording `StableLevelId` consumption within `CalculationIdentity` namespace.
4. **Dashboard Signal Presentation Components**:
   - Visual signal markers on Plotly candlestick charts (arrows/banners) and chronological Signal Inspection Table in Dash layout.

### 4.3 Proposed First Implementable Subset (Milestone 31):
- Implement the **Multi-Timeframe Confirmation Monitor** (offline LTF CHOCH/ISS pattern detection strictly scoped to existing `PENDING_ACTIVATION` and `REARMED_PENDING` states emitted by `ActivationSessionCoordinator`).
- Emits candidate confirmation events without performing premature arbitration or state mutation. Candidate arbitration and scoped usage ledger follow in Milestone 32.
