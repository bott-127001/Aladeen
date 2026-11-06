# Trade-Signal Business Logic & Acceptance Contract — Milestone 30

**Milestone**: Milestone 30 — Trade-Signal Business Logic Requirements and Acceptance Contract  
**Active Branch**: `requirements/trade-signal-acceptance`  
**Accepted Baseline Commit**: `0144ddb8150b4132a7b60d24698105d897514cb2` (Milestone 29 accepted)  
**Parent Documentation Commit**: `c159c6af10570739ded050e61be1b373fd98f084`  

> [!IMPORTANT]
> **Specification Authority & Provenance**:
> - **Primary Multi-Timeframe & Entry Confirmation Authority**: `docs/strategy/MTF-Analysis.pdf` (Version 1 — Consolidated rule record, 26 October 2026, 12:58 AM IST), transcribing `Entry_and_Confirmation_New_Rules.pdf` with approved user decisions.
>   - *Section 1*: Scope, Authority and Status (Disproven D1/H4/H1 trend alignment excluded; no agreement between timeframes required; stop loss/targets/position sizing are user responsibility).
>   - *Section 2*: Analysis Versus Trade Finding (TJL is only source of marked trade-finding levels; CHOCH/ISS serve analysis on HTF and entry confirmation on assigned LTF after TJL activation; zones are not independent trade setups).
>   - *Section 3*: Source Timeframes, Structure and Direction (D1, H4, H1 independently; TJL1 confirmed point 1, TJL2/A+ confirmed point 2; Bullish -> TJL1 Buy, TJL2 Buy; Bearish -> TJL1 Sell, TJL2 Sell; TJL1 follows source trend; same activation rule for TJL1 and TJL2).
>   - *Section 4*: Marked-Set Updates and Weekly Retention (Monday-to-Monday marking cycle; replacement on new 3-point set; retain levels if no new set on Monday; Monday alone does not delete, cancel, or reset usage; inherited zone-construction rules).
>   - *Section 5*: Tap and Activation (Any wick touch activates; close inside not required; unused, eligible level only; first tap starts confirmation search; repeated taps do not reset search; tap is not an entry signal).
>   - *Section 6*: Confirmation Mapping and Direction (D1 $\rightarrow$ H1, H4 $\rightarrow$ M5, H1 $\rightarrow$ M1; normal CHOCH or ISS; bullish requires fresh bullish normal CHOCH or bullish ISS; bearish requires fresh bearish normal CHOCH or bearish ISS; already-aligned trend is NOT sufficient; detection rules unchanged on assigned confirmation timeframes).
>   - *Section 7*: Confirmation Timing and Entry (Pattern may start before first tap, but must confirm on tap candle or afterward; confirmation completed before activation cannot be reused; tap candle may confirm; enter immediately at confirmation close without waiting for retest; confirming candle need not close inside zone; conceptual entry timing).
>   - *Section 8*: Competing Activations and Tie-Breakers (First valid confirmation by close timestamp wins; simultaneous close chooses lower timeframe: M1 before M5 before H1; simultaneous same-source chooses TJL2 / A+; winning entry marks level used and cancels all other pending activations).
>   - *Section 9*: Cancellation and Reactivation (Replacement TJL set cancels old set; source main CHOCH immediately cancels old-direction activation; external entry cancels pending activations; price must leave zone and retouch to reactivate; used level cannot reactivate).
>   - *Section 10*: One Trade Per Level (Each particular level supplies at most one trade; touch is not usage; entry commit is usage; repeated taps, cancellations, and Monday resets do not reset used status).
>   - *Section 11*: User-Owned Risk and Management (Stop loss, targets, position sizing, trade management outside specification).
>   - *Section 12*: Complete Q&A Record (Questions 1–25).
> - **Approved Clarifications Authority**: [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (User approvals dated 4 November 2026, recorded in project artifact `aladin_topg_dashboard_e6a30e5e.plan.md`):
>   - `OPEN-03`: Invalidation Precedence at Shared Close (Source invalidation/replacement applied before evaluating entry eligibility).
>   - `OPEN-04`: Candle Timestamp Intervals & Wick Boundaries (Half-open intervals `[open_time, close_time)`; level cannot retroactively claim earlier candle wick; unknown ordering marks `UNKNOWN_ORDER`).
>   - `OPEN-05`: Rearming After Out-of-Zone Cancellation (When cancellation occurs while price is observed outside zone, next observed touch rearms).
>   - `OPEN-06`: Single Price Basis & Physical Observation (Configured Bid/Ask/Mid; actual observed print inside `[lower, upper]`; zero path interpolation).
>   - `OPEN-07`: Multiple Confirmation Evidence Consolidation (When a single entry setup possesses both CHOCH and ISS confirmation evidence, record both confirmation identifiers on that single entry record; do NOT generate two duplicate or competing entry signals).
>   - `OPEN-08`: Independent Engine Configuration & Manual Start Validation (Isolated runs; no silent start inheritance; clean calculation runs).
>   - `OPEN-09`: Origin, Evidence Status & Immutable Signals (Immutable published records; versioned replay from prior valid dependency).
>   - `OPEN-10`: Native MT5 Boundaries & Persisted Source Calendar (Native MT5 bar times; weekly boundary within broker source calendar).
>   - `OPEN-11`: Chronological Signal Listing Without Position Gating (List every conceptual trade signal chronologically as it occurs, including subsequent opposite-side signals; analysis engine must not filter, suppress, or gate signals based on hypothetical open positions).
>   - `OPEN-12`: Event Ordering at Coarse Timestamp T (Later event rearms only after winning entry commit finalizes).
> - **Prerequisite Specifications**:
>   - [`docs/requirements/msm-acceptance.md`](msm-acceptance.md)
>   - [`docs/requirements/choch-acceptance.md`](choch-acceptance.md)
>   - [`docs/requirements/iss-acceptance.md`](iss-acceptance.md)
>   - [`docs/requirements/tjl-acceptance.md`](tjl-acceptance.md)
>   - [`docs/requirements/activation-acceptance.md`](activation-acceptance.md)
> - **Strict Safety & Scope Boundary**: Requirements reconciliation, fixture design, and acceptance contract specification only. Strictly **zero runtime signal engine implementation, zero UI order execution, zero MT5 live trading calls, zero live account modification, zero automated trading, and zero merging to `main`**.

---

## 1. Domain Terminology & Entity Lifecycle

To prevent ambiguity, the trade-signal business logic defines five distinct conceptual entities across the decision pipeline:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 1. Source Structural Level (TJL Engine: D1, H4, H1)                             │
│    - Identified by physical StableLevelId: (source_tf, source_open_time, side)  │
│    - Status: INACTIVE_ELIGIBLE, LABELS_ONLY, or USED                            │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │ Price Touch Print
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 2. Pending Activation (Activation Engine)                                       │
│    - First touch transitions level to PENDING_ACTIVATION                        │
│    - Maps designated confirmation timeframe (D1->H1, H4->M5, H1->M1)            │
│    - Non-resetting across subsequent touches                                    │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │ Qualifying Pattern Confirms On/After Tap
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 3. Confirmed Setup Candidate (Signal Engine Evaluation)                         │
│    - Lower-timeframe directional pattern (Bullish/Bearish Normal CHOCH or ISS) │
│    - Evaluated at confirmation candle close time                                │
│    - Invalidation pre-checks: source replacement, source main CHOCH             │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │ Arbitration / Tie-Breakers (if competing)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 4. Selected Winning Entry & Published Signal (Dashboard Presentation)           │
│    - Earliest close timestamp wins; ties broken by lower TF, then TJL2 (A+)     │
│    - Emits immutable PublishedTradeSignal: BUY or SELL                          │
│    - Consumes source physical level: marks StableLevelId as USED in ledger      │
│    - Cancels all other pending activations across D1, H4, and H1               │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │ STRICT SAFETY BOUNDARY (OUT OF SCOPE)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 5. Executed Trade (Live Broker Order Placement)                                 │
│    - [STRICTLY FORBIDDEN / 0% IMPLEMENTED / NON-PRODUCTION BOUNDARY]            │
│    - Stop-loss, take-profit, position sizing, order routing, fills              │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Distinction of Events (Directive 4 Reconciliation):
- **Signal Publication**: The deterministic generation and display of a conceptual trade signal on the read-only dashboard.
- **Entry Selection**: The arbitration decision where the earliest qualifying candidate wins and other pending activations are cancelled.
- **Usage Consumption**: The permanent state transition where the winning physical `StableLevelId` is marked `USED` in the usage ledger.
- **Executed Trade**: Broker order placement and execution. **This does NOT exist in the Aladeen dashboard**. Published signals explicitly carry `is_broker_execution: false` and `signal_type: "CONCEPTUAL_ANALYSIS_SIGNAL"`.

---

## 2. Nine-Stage Decision Chain Specification (Directive 3)

### Stage 1: Eligible Source Context
- **Timeframes**: D1, H4, and H1 source timeframes operate independently (`MTF-Analysis.pdf` §3).
- **Structure & Direction**:
  - Bullish Structure $\rightarrow$ Both TJL1 and TJL2 qualify for **BUY** trade signals (`MTF-Analysis.pdf` §3).
  - Bearish Structure $\rightarrow$ Both TJL1 and TJL2 qualify for **SELL** trade signals (`MTF-Analysis.pdf` §3).
  - TJL1 strictly follows the source structure trend direction. It does not trade in the opposite direction merely because its source point is a high or low (`MTF-Analysis.pdf` §3, Q&A 20).
- **Set Membership**: Only zones belonging to the active `CurrentEligibleSet` (`SET_1` or `SET_2`) are eligible. At continuation `t1`, the current set remains eligible; labels-only zones awaiting set replacement are ineligible (`docs/requirements/tjl-acceptance.md` §5.2).

### Stage 2: Activation Prerequisite
- **Activation Requirement**: A level must hold an active `PENDING_ACTIVATION` state produced by a valid physical price touch (`MTF-Analysis.pdf` §5).
- **Physical Touch**: Any wick touch (high/low price print inside or on inclusive zone boundaries `[lower_edge, upper_edge]`) is sufficient; a close inside is not required (`MTF-Analysis.pdf` §5, Q&A 11).
- **Eligibility Check**: Only an unused level (`used_status == false`) can activate. A previously used level is permanently dead (`MTF-Analysis.pdf` §5, §10).
- **First Tap Reference**: The first tap timestamp establishes the lower bound for confirmation search. Repeated touches during pending activation do not restart or reset the search (`MTF-Analysis.pdf` §5, Q&A 13).

### Stage 3: Confirmation Requirements & Mapping
- **Mapping Table** (`MTF-Analysis.pdf` §6):
  | Source Timeframe | Assigned Confirmation Timeframe | Accepted Confirmation Patterns |
  |---|---|---|
  | **D1** | **H1** | Normal CHOCH or ISS |
  | **H4** | **M5** | Normal CHOCH or ISS |
  | **H1** | **M1** | Normal CHOCH or ISS |
- **Directional Concordance**:
  - Intended BUY signal $\rightarrow$ Requires **Bullish Normal CHOCH** or **Bullish ISS** (`MTF-Analysis.pdf` §6, Q&A 4).
  - Intended SELL signal $\rightarrow$ Requires **Bearish Normal CHOCH** or **Bearish ISS** (`MTF-Analysis.pdf` §6, Q&A 4).
  - An opposite-direction confirmation is strictly rejected (`REJECTED_DIRECTION_MISMATCH`).
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

### Stage 5: Competing Candidates & Tie-Breaking Hierarchy
When multiple levels are simultaneously pending activation across D1, H4, and H1 (`MTF-Analysis.pdf` §8):
1. **Rule 1 (Earliest Close Timestamp Wins)**:
   - The candidate with the earliest completed confirmation candle close timestamp wins, regardless of timeframe (`MTF-Analysis.pdf` §8, Q&A 15).
2. **Rule 2 (Simultaneous Close Timestamp $\rightarrow$ Lower Timeframe Wins)**:
   - If competing valid candidates share the exact same closing timestamp, prefer the lower confirmation timeframe: **M1 before M5 before H1** (`MTF-Analysis.pdf` §8, Q&A 18).
3. **Rule 3 (Simultaneous Same-Source TJL1 vs TJL2 $\rightarrow$ TJL2 / A+ Wins)**:
   - If TJL1 and TJL2 from the same source timeframe qualify at the exact same timestamp, choose **TJL2** because it is A+ (`MTF-Analysis.pdf` §8, Q&A 22).
4. **Rule 4 (Single Winning Entry Selection)**:
   - Exactly one candidate is selected. Its source level is marked USED, and all other pending activations are cancelled (`MTF-Analysis.pdf` §8, Q&A 16).

### Stage 6: Signal Publication & Determinism
- **Publication Event**:
  - A published trade signal is emitted at the exact completed close timestamp of the winning confirmation candle.
  - Required Fields: `signal_id`, `timestamp_utc`, `symbol`, `signal_side` (BUY/SELL), `source_timeframe`, `source_level_role` (TJL1/TJL2), `stable_level_id`, `confirmation_timeframe`, `confirmation_pattern_type` (CHOCH/ISS), `confirmation_event_ids`, `entry_price` (confirmation close price), `is_broker_execution: false`.
- **Multiple Confirmation Consolidation (`OPEN-07`)**:
  - If both CHOCH and ISS confirm on the same confirmation candle, record both identifiers on a single consolidated signal. Never emit duplicate signals (`OPEN-07`).
- **Immutable Publication (`OPEN-09`)**:
  - Published signals are strictly immutable. Correcting prior data requires a versioned replay (`OPEN-09`).
- **Chronological Listing Without Position Gating (`OPEN-11`)**:
  - Signals are published chronologically as they occur, including subsequent opposite-side signals. The engine does NOT filter or suppress signals based on hypothetical open positions (`OPEN-11`).

### Stage 7: Usage Accounting & Permanent Consumption
- **One Trade Per Level Contract (`MTF-Analysis.pdf` §10)**:
  - Each physical level (`StableLevelId`) can supply **at most one trade** in its entire lifetime (`MTF-Analysis.pdf` §10).
  - Taps, cancellations, repeated touches, and weekly roll-overs do NOT consume a level; only an accepted winning entry commit consumes it (`MTF-Analysis.pdf` §10).
  - A used level is permanently dead and can never reactivate or produce another signal, even if price touches it again or it is retained into subsequent weeks (`MTF-Analysis.pdf` §4, §10).

### Stage 8: Repeat Signals & Rearming Semantics
- **Rearming Unused Cancelled Levels (`MTF-Analysis.pdf` §9, `OPEN-05`)**:
  - An unused level cancelled because another timeframe's entry won may reactivate if it is still a member of the current eligible set (`MTF-Analysis.pdf` §9, Q&A 17).
  - **Path B (Already Outside)**: If price was already outside the zone boundaries at the moment of cancellation, the very next observed price touch rearms activation (`OPEN-05`).
  - **Path A (Inside Zone at Cancellation)**: If price was inside the zone at cancellation, price must first leave the zone; remaining or lingering inside does NOT count (`MTF-Analysis.pdf` §9, Q&A 25). The next touch after departure rearms activation.
- **Fresh Confirmation Required**:
  - A reactivated level requires a fresh qualifying confirmation on its new tap candle or afterward. Prior confirmations cannot be recycled (`MTF-Analysis.pdf` §9).
- **Coarse Timestamp T Event Ordering (`OPEN-12`)**:
  - At a shared coarse timestamp T, rearming of a cancelled level can only occur strictly after the winning entry commit has finalized (`OPEN-12`). Recycled tap evidence is strictly rejected.

### Stage 9: Latest/History Presentation & Deterministic Replay
- **Signal History Retention**:
  - All published signals are retained in an immutable chronological ledger.
  - The dashboard displays the latest active signal status alongside historical signals.
- **Deterministic Replay (`OPEN-09`)**:
  - Replaying market data from the configured start candle must produce identical signals with identical timestamps, identifiers, and sequences.

---

## 3. Preserved Strategy Gaps & Fail-Closed Handling (Directive 5)

Per Perplexity directives, the following unresolved strategy questions are handled with explicit fail-closed logic:

| Unresolved Issue | Affected Scope | Fail-Closed Policy | Minimal Decision for Samarth |
|---|---|---|---|
| **CHOCH $c_1 == p_2$ Close Equality** | Source MSM/CHOCH engine state freezing | If source structure freezes in unresolved ambiguity, signal evaluation for that source timeframe is immediately frozen (`BLOCKED_SOURCE_UNRESOLVED`). No signal emitted. | Formally reconcile whether $c_1 == p_2$ constitutes an upward continuation, downward reversal, or containment freeze. |
| **ISS Multi-Candle Pullback Qualification** | Lower-timeframe ISS confirmation setups | Candidate ISS confirmations on H1, M5, or M1 involving multi-candle pullbacks are marked `UNRESOLVED_CONFIRMATION_GAP`. No signal emitted. Only standard single-candle pullback ISS setups qualify. | Formally reconcile multi-candle pullback rules for ISS confirmation. |
| **Intra-Candle Ambiguity (`OPEN-04`)** | Coarse bars where tap and confirmation occur on the same candle without sub-bar tick ordering | If sub-bar order cannot be established with certainty, mark `UNKNOWN_ORDER` and suppress signal publication. | Confirm whether 1-minute tick/M1 sub-bars are required for intraday tap ordering. |

---

## 4. Integration Gap Assessment (Directive 7.5)

### 4.1 Currently Available Engine Outputs (Accepted Baselines):
1. **MSM Engine (`MSMEngine`)**: Confirmed swing highs/lows, trend status, and validated candle sequence.
2. **CHOCH Detector (`ChochDetector`)**: Directional CHOCH events, continuation resets, and unresolved freeze flags.
3. **ISS Engine (`ISSEngine`)**: 5-point structural shifts, isolated tracking records, and terminal states.
4. **TJL Coordinator (`TJLCoordinator`)**: Current eligible sets (`tjl1_zone`, `tjl2_zone`), t1 retention, and t2 replacement records.
5. **Activation Engine (`ActivationSessionCoordinator`)**: Ingestion of physical price prints, `PENDING_ACTIVATION` state tracking, and rearming state machines.

### 4.2 Missing Components Required for Signal Generation:
1. **Multi-Timeframe Confirmation Monitor**:
   - Subsystem to ingest lower-timeframe candle streams (H1 for D1, M5 for H4, M1 for H1) and execute real-time CHOCH/ISS pattern matching scoped to pending activations.
2. **Candidate Arbitration Engine**:
   - Cross-timeframe comparator implementing the 4-level tie-breaking hierarchy (earliest close $\rightarrow$ lower TF $\rightarrow$ TJL2/A+).
3. **Usage Ledger Subsystem**:
   - Thread-safe, persistent ledger recording `StableLevelId` consumption, preventing double-trade execution across sessions.
4. **Dashboard Signal Presentation Components**:
   - Visual signal markers on Plotly candlestick charts (arrows/banners) and chronological Signal Inspection Table in Dash layout.

### 4.3 Proposed Implementation Order (Milestone 31+):
1. **Milestone 31**: Multi-Timeframe Confirmation Engine (Offline LTF CHOCH/ISS pattern detection mapped to pending TJL activations).
2. **Milestone 32**: Candidate Arbitration & Signal Generation Engine (Tie-breakers, cancellation propagation, and usage ledger).
3. **Milestone 33**: Read-Only Dashboard Signal Presentation & Inspection UI (Chart overlays and chronological signal inspection table).
4. **Milestone 34**: Controlled Browser End-to-End Signal Verification (Playwright browser test suite covering full signal lifecycle).
