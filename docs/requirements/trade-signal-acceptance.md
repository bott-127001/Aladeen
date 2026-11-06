# Trade-Signal Business Logic & Acceptance Contract — Milestone 30

**Milestone**: Milestone 30 — Trade-Signal Business Logic Requirements and Acceptance Contract  
**Active Branch**: `requirements/trade-signal-acceptance`  
**Accepted Baseline Commit**: `0144ddb8150b4132a7b60d24698105d897514cb2` (Milestone 29 accepted)  
**Parent Documentation Commit**: `2b356489ddefc1deb168e4b8b83c9febb3ed9d07` (HANDOFF-088)  

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
>   - Operational engineering proposals (e.g. candidate setup grouping key, transaction commit boundary, completeness violation handling) are explicitly labeled as implementation contracts requiring acceptance, distinguished from verbatim source strategy rules.
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
│    - Canonical activation_id: ACT_G{gen}[{len}:engine][{len}:tf][{len}:sym]...         │
│    - Maps designated confirmation timeframe (D1->H1, H4->M5, H1->M1)                   │
│    - Non-resetting across subsequent touches within the same activation generation     │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │ Qualifying Pattern Confirms On/After Tap
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. Confirmed Setup Candidate (Signal Engine Evaluation)                                │
│    - Lower-timeframe directional pattern (Bullish/Bearish Normal CHOCH or ISS)        │
│    - Explicit CandidateSetupKey tracking full activation, set, and confirmation stream │
│    - Consolidates CHOCH + ISS under shared confirmation configuration (OPEN-07)        │
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
│        * Emits immutable PublishedTradeSignal: BUY or SELL with entry_reference_price  │
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
- **Identity Disambiguation**:
  The following four concepts are strictly distinct and must never be conflated:
  1. **Structural Role**: `"TJL1"` or `"TJL2_A_PLUS"` (structural role within a TJL set).
  2. **Canonical Member Key**: Length-prefixed member identifier `format_member_key(set_id, role)` e.g. `MK[15:SET_20261001_H4][4:TJL1]`.
  3. **Activation ID**: Length-prefixed transient activation identifier `format_activation_id(engine_id, source_timeframe, symbol, set_id, role, generation_seq)` e.g. `ACT_G01[15:ACT_ENGINE_DEMO][2:H4][6:EURUSD][15:SET_20261001_H4][4:TJL1]`.
  4. **Physical Level ID**: Full 4-tuple physical identity `StableLevelId(symbol_feed_id, source_timeframe, source_open_time, side)`.
  *Note*: The activation ID embeds engine, timeframe, symbol, set, role, and generation; it does not embed the full `StableLevelId`. Their associations are maintained explicitly via structured metadata.
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
- **Continuous Confirmation Detection**:
  - Confirmation engines run continuous pattern recognition over their own independently configured candle history from their established start candles.
  - They do **NOT** pause, reset, or restart pattern recognition when a physical tap occurs.
  - A confirmation pattern that begins forming before activation touch and completes on the tap candle or afterward is fully valid and permitted (`MTF-Analysis.pdf` §7, Q&A 12, `sig_06`).
- **Directional Concordance**:
  - Intended BUY signal $\rightarrow$ Requires **Bullish Normal CHOCH** or **Bullish Confirmed ISS** (`MTF-Analysis.pdf` §6, Q&A 4).
  - Intended SELL signal $\rightarrow$ Requires **Bearish Normal CHOCH** or **Bearish Confirmed ISS** (`MTF-Analysis.pdf` §6, Q&A 4).
  - An opposite-direction confirmation is strictly rejected (`REJECTED_DIRECTION_MISMATCH`).
- **Authoritative Confirmation Provenance**:
  - Merely being an event emitted by an engine module is insufficient. A valid confirmation requires:
    1. Valid structural provenance: derived from real underlying candle sequence meeting all strategy definitions (`Choch.pdf`, `ISS.pdf`, `Market Structure Marking.docx`).
    2. Valid completion status: `is_completed: true` on the confirmation candle close.
    3. Resolved dependencies: zero unresolved structural ambiguity in source or confirmation calculations.
  - **Isolated tracking records** (`ISOLATED_TRACKING_ONLY`) or synthetic completion evidence do NOT constitute entry confirmation (`REJECTED_ISOLATED_TRACKING_NOT_CONFIRMATION`).
  - **Unresolved detection paths** (including multi-candle pullback ambiguity where strategy rules remain unreconciled) fail closed as `BLOCKED_UNRESOLVED_CONFIRMATION_GAP` and emit no trade signals. No candle-count heuristic is invented.
- **Fresh Transition Required**:
  - An already-aligned trend is NOT sufficient; a fresh CHOCH or ISS transition event is mandatory (`MTF-Analysis.pdf` §6, Q&A 19).
- **Same-Candle Causality & Evidence Contract**:
  - `MTF-Analysis.pdf` §7 (Q&A 12) provides that the tap candle may also confirm entry if it confirms a valid pattern.
  - Three distinct causal timing cases apply:
    * **Case A (Exact Observed Print Preceding Close)**: Exact observed touch timestamp is strictly prior to confirmation close timestamp ($t_{tap} < t_{close}$) $\rightarrow$ Eligible timing (`sig_03`).
    * **Case B (Shared Coarse Timestamp with Monotonic Sequence Evidence)**: Tap and confirmation share a coarse candle timestamp interval, but authoritative monotonic sequence indexing proves touch preceded pattern completion ($seq_{tap} < seq_{conf}$) $\rightarrow$ Eligible timing (`sig_30`). Missing sub-bar timestamps do NOT suppress signals when sequence evidence establishes order.
    * **Case C (OHLC Overlap without Sequence Evidence)**: Tap and confirmation share a coarse bar, but the feed provides only OHLC bounds without intra-bar sequence ordering or sub-bar print timestamps $\rightarrow$ Fails closed as `UNKNOWN_ORDER` (`sig_22`). Missing authoritative touch or ordering evidence blocks the transition. Timestamp precision alone does not determine eligibility. This is an evidence limitation, not an unresolved strategy choice.
  - A confirmation completed strictly before activation cannot be reused (`PRE_ACTIVATION_CONFIRMATION_REJECTED`, `sig_05`).
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
  *Note*: Cancellation targets are strictly **activation IDs** (identifying active or pending activations that were open at that moment, including those that produced zero confirmation candidates). Cancellation targets are never candidate IDs (`sig_09`, `sig_10`, `sig_11`, `sig_12`).

### Stage 5: Declared Arbitration Domain, Completeness & Tie-Breaking
- **Three-Tier Calculation Namespace Separation**:
  To prevent cross-run pollution and clarify replay semantics, three distinct identities are maintained:
  1. **Strategy / Configuration Identity**: The strategy parameters tuple:  
     `(server, symbol, price_basis, timeframe_configuration, manual_start_time, rule_version)`.
  2. **Calculation Namespace / Domain Session**: The concrete runtime execution instance:  
     `DomainSession = (calculation_identity, session_id, sequence_domain_run_id)`.  
     Usage consumption, level states, and pending activations are strictly scoped to this `DomainSession`. Independent research sessions or different manual start times do NOT cross-consume levels (`sig_35`).
  3. **Replay Version**: A versioned calculation run (`revision_id` / `run_version`). A fresh recalculation from historical event sequence rebuilds its own clean usage ledger from scratch; it does NOT mutate prior versioned ledgers or leak consumption.
- **Evidence Completeness Defined by Due Events**:
  - Completeness at timestamp $T$ does NOT require every higher timeframe to close simultaneously. An ordinary H1, H4, or D1 bar normally forming across $T$ is NOT missing evidence.
  - Completeness requires: **All events, bars, and invalidations due at or before $T$ across all participating timelines in the declared domain are accounted for**.
  - An M1 confirmation at 08:05:00 is fully complete and eligible to arbitrate, even while H1 `[08:00, 09:00)` is forming, provided that all M1, M5, H1, H4, and D1 data *due* at or before 08:05:00 has been received (`sig_28`).
  - If a due event is missing (e.g. feed gap, unclosed bar due at $T$, or unreceived source replacement), arbitration is blocked fail-closed (`BLOCKED_INCOMPLETE_EVIDENCE_COVERAGE`, `sig_29`).
- **Order-Independent Deterministic Tie-Breaking**:
  - Competing candidates evaluated at timestamp $T$ are deterministically sorted by:
    1. **Primary**: Earliest completed confirmation `close_timestamp` (ascending) (`MTF-Analysis.pdf` §8, Q&A 15).
    2. **Secondary (Simultaneous Timestamps)**: Lower confirmation timeframe (`M1` before `M5` before `H1`) (`MTF-Analysis.pdf` §8, Q&A 18).
    3. **Tertiary (Simultaneous Same-Source TJL1 vs TJL2)**: Prefer **TJL2 / A+** over TJL1 (`MTF-Analysis.pdf` §8, Q&A 22).
  - The winner is selected strictly by this hierarchy (`sig_09`, `sig_10`, `sig_11`). Event delivery arrival order has zero strategy priority (`sig_27`).

### Stage 6: Candidate Identity, Setup Grouping, Schemas, and Atomic Commit

#### 6.1 Explicit Candidate / Setup Identity (`CandidateSetupKey`)
To eliminate ambiguous grouping and prevent conflation across distinct sets, confirmation configurations, or sessions, candidate setups are identified by a canonical length-prefixed key:
```
CandidateSetupKey = CSK[{len(domain_session_id)}:{domain_session_id}][{len(revision_id)}:{revision_id}][{len(activation_id)}:{activation_id}][{len(source_member_key)}:{source_member_key}][{len(confirmation_config_id)}:{confirmation_config_id}][{len(confirmation_candle_id)}:{confirmation_candle_id}][{len(confirmation_close_iso)}:{confirmation_close_iso}]
```
Where:
- `domain_session_id`: Runtime calculation namespace `(calculation_identity, session_id, sequence_domain_run_id)`.
- `revision_id`: Replay version / run version.
- `activation_id`: Canonical length-prefixed activation identifier `format_activation_id()` embedding engine, timeframe, symbol, set, role, and generation.
- `source_member_key`: Canonical length-prefixed member key `format_member_key()` embedding set and role.
- `confirmation_config_id`: Shared confirmation stream / configuration identity (common timeframe, market data feed, rule version, start candle, e.g. `CONF_CFG_EURUSD_M5_v1`).
- `confirmation_candle_id`: Canonical confirmation bar identifier (e.g. `EURUSD:M5:20261002T083500Z`).
- `confirmation_close_iso`: UTC ISO 8601 close timestamp of the confirming candle.

#### 6.2 Proposed Setup Grouping Policy (`OPEN-07` Operational Proposal)
- *Engineering Proposal Label*: In accordance with `OPEN-07`, when a single entry setup possesses both CHOCH and ISS confirmation evidence, both confirmation identifiers are recorded on a single signal record to avoid duplicate entries.
- *Separation of Shared Stream vs Detector Identity*:
  * **Shared Configuration Context**: The confirmation stream/configuration identity (`confirmation_config_id`) represents the shared candle timeline, data resolution, start candle, and parameter set. Both CHOCH and ISS detectors evaluating that timeline share this configuration ID.
  * **Individual Evidence Provenance**: Each individual confirmation event retains its detector/producer identity (`producer_id="CHOCH_DETECTOR_v1"`, `pattern_type="CHOCH"` vs `producer_id="ISS_ENGINE_v1"`, `pattern_type="ISS"`), its unique `event_id`, and its confirmation close price.
- *Grouping Rule*: Multiple qualifying confirmation events consolidate into a single candidate setup if and only if they share the exact same `CandidateSetupKey`.
- Because `CandidateSetupKey` uses the shared `confirmation_config_id` (rather than a pattern-specific detector ID), CHOCH and ISS events completing on the same stream at the same close consolidate cleanly into one setup (`sig_18`).
- Different confirmation stream configurations (e.g. different parameters or start candles) produce distinct `confirmation_config_id`s, generating distinct setup keys and preventing conflation (`sig_39`).
- Persistent physical levels across different sets receive distinct `activation_id`s, producing distinct setup keys without cross-set collision (`sig_38`).

#### 6.3 Required Candidate Record Schema (`CandidateSignalRecord`)
Every candidate evaluated in arbitration must supply the following explicit typed fields:
1. `candidate_id`: str (canonical length-prefixed unique candidate identifier).
2. `setup_key`: str (serialized canonical `CandidateSetupKey`).
3. `domain_session_id`: str.
4. `revision_id`: str.
5. `activation_id`: str (canonical activation identifier).
6. `source_level_id`: `StableLevelId` (full 4-tuple physical identity).
7. `source_timeframe`: str (`"D1"` | `"H4"` | `"H1"`).
8. `source_set_id`: str (TJL set identifier).
9. `source_role`: str (`"TJL1"` | `"TJL2_A_PLUS"`).
10. `signal_side`: str (`"BUY"` | `"SELL"`).
11. `confirmation_timeframe`: str (`"H1"` | `"M5"` | `"M1"`).
12. `confirmation_close_timestamp`: str (UTC ISO 8601).
13. `entry_reference_price`: float (confirmation-close price of confirming candle).
14. `price_basis`: str (`"BID"` | `"ASK"` | `"MID"`).
15. `price_provenance`: str (`"CONFIRMATION_CANDLE_CLOSE"`).
16. `confirmation_event_ids`: Tuple[str, ...] (individual confirmation event IDs).
17. `confirmation_patterns`: Tuple[str, ...] (`"CHOCH"`, `"ISS"`).
18. `is_consolidated`: bool (True if both CHOCH and ISS present).
19. `timeframe_rank`: int (M1=1, M5=2, H1=3).
20. `role_rank`: int (TJL2_A_PLUS=1, TJL1=2).

#### 6.4 Required Published Signal Record Schema (`PublishedTradeSignal`)
Every signal committed and published on the dashboard must supply the following explicit typed fields:
1. `signal_id`: str (canonical length-prefixed unique signal identifier).
2. `commit_id`: str (atomic transaction commit identifier).
3. `domain_session_id`: str.
4. `revision_id`: str.
5. `winning_candidate_id`: str.
6. `consumed_level_id`: `StableLevelId` (physical level consumed by this signal).
7. `activation_id`: str (activation ID of winning setup).
8. `source_timeframe`: str.
9. `source_set_id`: str.
10. `source_role`: str.
11. `signal_side`: str (`"BUY"` | `"SELL"`).
12. `confirmation_timeframe`: str.
13. `signal_timestamp`: str (UTC ISO 8601, equals confirmation candle close).
14. `entry_reference_price`: float (confirmation-close price of confirming candle).
15. `price_basis`: str (`"BID"` | `"ASK"` | `"MID"`).
16. `price_provenance`: str (`"CONFIRMATION_CANDLE_CLOSE"`).
17. `confirmation_event_ids`: Tuple[str, ...].
18. `confirmation_patterns`: Tuple[str, ...].
19. `cancelled_activation_ids`: Tuple[str, ...] (canonical activation IDs of all other pending activations cancelled by this commit across D1/H4/H1).
20. `is_broker_execution`: bool = False (Mandatory safety invariant).
21. `signal_type`: str = `"CONCEPTUAL_ANALYSIS_SIGNAL"` (Mandatory safety invariant).
22. `publication_status`: str = `"FINALIZED_IMMUTABLE"`.

#### 6.5 Atomic Conceptual Commit Transaction
- The winning entry commit is an atomic, idempotent operation within the active `DomainSession`:
  1. Designates the winning candidate setup.
  2. Consumes the winning physical level: permanently marks `StableLevelId` as `USED` in the scoped usage ledger.
  3. Records and publishes the immutable `PublishedTradeSignal`.
  4. Routes cancellation events across all other pending activations (`PENDING_ACTIVATION` and `REARMED_PENDING`) across D1, H4, and H1 within the active domain session.
- Failure at any step rolls back completely (zero partial commits).

#### 6.6 Finalization, Retries, and Late Evidence Policy
- **Identical Already-Accounted Evidence**: Retrying an identical commit request or receiving an already-accounted confirmation event succeeds idempotently, returning the existing record without duplicate signal emission or double consumption (`sig_33`).
- **Conflicting Retry Rejection**: Retrying a commit with conflicting content for the same `commit_id` is strictly rejected fail-closed (`COMMIT_CONFLICT_REJECTED`, `sig_34`).
- **Evidence Arriving Before Finalization**: Any candidate arriving before batch finalization at timestamp $T$ is included in the candidate evaluation pool for timestamp $T$ (`sig_31`).
- **New Due Evidence Arriving After Finalization (Coverage Violation)**:
  - If *new*, relevant confirmation evidence arrives whose due timestamp was $\le T$ (i.e. it was due at or before the batch's declared completeness boundary, but arrived late):
    * This constitutes a **completeness/coverage violation** (`COMPLETENESS_COVERAGE_VIOLATION` / `LATE_DUE_EVIDENCE_ARRIVED`). The earlier completeness determination at $T$ was incomplete/erroneous.
    * The late evidence is **retained as a diagnostic** on the session ledger.
    * **Published records are never mutated in place**; the published signal at $T$ remains immutable.
    * **Subsequent dependent decisions** on the affected symbol/domain timeline are **blocked fail-closed** until versioned reconciliation is performed (e.g. recalculation/replay under a new `revision_id` / `run_version`), without freezing unrelated symbols or independent domains.
    * Such evidence is **never silently discarded**, because it could have changed the approved earliest-confirmation winner or level consumption (`sig_37`).
- **Future-Timestamp Confirmation Eligibility ($T_{later} > T$)**:
  - A confirmation completing on a later candle ($T_{later} > T$) is NOT globally suppressed or discarded as "ignored".
  - It is evaluated in its own batch at $T_{later}$ against current activation state at $T_{later}$.
  - The earlier signal at $T$ is immutable and cannot be mutated by later events (`OPEN-09`).
  - If the level was consumed by the signal at $T$, evaluation at $T_{later}$ sees `used_status == true` and rejects with `LEVEL_ALREADY_USED` (`sig_32`). If another level or rearmed level is active, it evaluates normally.

### Stage 7: Scoped Usage Accounting & Namespace Isolation
- **One Trade Per Level Contract (`MTF-Analysis.pdf` §10)**:
  - Each physical level (`StableLevelId`) can supply **at most one trade** in its entire lifetime (`MTF-Analysis.pdf` §10).
  - Taps, cancellations, repeated touches, and weekly roll-overs do NOT consume a level; only an accepted atomic conceptual commit consumes it (`MTF-Analysis.pdf` §10).
  - A used level is permanently dead and can never reactivate or produce another signal, even if price touches it again or it is retained into subsequent weeks (`MTF-Analysis.pdf` §4, §10, `sig_13`).
- **Session Namespace Isolation**:
  - Usage ledger is strictly scoped to `DomainSession`. Independent sessions or distinct start candles maintain isolated ledgers and do NOT cross-consume levels (`OPEN-08`, `sig_35`).

### Stage 8: Repeat Signals & Rearming Semantics
- **Rearming Unused Cancelled Levels (`MTF-Analysis.pdf` §9, `OPEN-05`)**:
  - An unused level cancelled because another timeframe's entry won may reactivate if it is still a member of the current eligible set (`MTF-Analysis.pdf` §9, Q&A 17).
  - **Path B (Already Outside)**: If price was already outside the zone boundaries at the moment of cancellation, the very next observed price touch transitions the level to `REARMED_PENDING` (`OPEN-05`, `sig_14`).
  - **Path A (Inside Zone at Cancellation)**: If price was inside the zone at cancellation, price must first leave the zone; remaining or lingering inside does NOT count (`MTF-Analysis.pdf` §9, Q&A 25). The next touch after departure transitions the level to `REARMED_PENDING` (`sig_15`).
- **Fresh Confirmation Required**:
  - A rearmed level requires a fresh qualifying confirmation on its new tap candle or afterward. Prior confirmations cannot be recycled (`MTF-Analysis.pdf` §9).
- **Coarse Timestamp T Event Ordering (`OPEN-12`)**:
  - At a shared coarse timestamp T, rearming of a cancelled level can only occur strictly after the winning entry commit has finalized (`OPEN-12`). Recycled tap evidence is strictly rejected.

### Stage 9: Latest/History Presentation & Deterministic Replay
- **Signal History Retention**:
  - All published signals are retained in an immutable chronological ledger.
  - The dashboard displays the latest active signal status alongside historical signals (`OPEN-11`, `sig_19`).
- **Deterministic Replay (`OPEN-09`)**:
  - Replaying market data from the configured start candle must produce identical signals with identical timestamps, identifiers, and sequences (`sig_25`).

---

## 3. Preserved Strategy Gaps & Fail-Closed Handling

The following unresolved strategy questions are handled with explicit fail-closed logic:

| Unresolved Issue | Affected Scope | Fail-Closed Policy | Minimal Decision for Samarth |
|---|---|---|---|
| **CHOCH $c_1 == p_2$ Close Equality** | Source MSM/CHOCH engine state freezing | If source structure freezes in unresolved ambiguity, signal evaluation for that source timeframe is immediately frozen (`BLOCKED_SOURCE_UNRESOLVED`). No signal emitted. | Formally reconcile whether $c_1 == p_2$ constitutes an upward continuation, downward reversal, or containment freeze. |
| **ISS Multi-Candle Pullback Qualification** | Lower-timeframe ISS confirmation setups | Candidate ISS confirmations involving multi-candle pullbacks where strategy rules remain unclarified fail closed as `BLOCKED_UNRESOLVED_CONFIRMATION_GAP`. No signal emitted. | Formally reconcile whether multi-candle pullback ISS patterns qualify as valid entry confirmation. |

### Technical Evidence Limitations (Non-Strategy Invariants):
- **Missing Authoritative Touch or Ordering Evidence**:
  - On shared candle intervals where tap and confirmation occur on the same coarse bar without sub-bar print timestamps or sequence evidence, the transition is blocked fail-closed as `UNKNOWN_ORDER` (`sig_22`).
  - Missing authoritative touch or ordering evidence blocks the affected transition. Timestamp precision alone does not determine eligibility; where discrete monotonic sequence index is available, order is established authoritatively (Case B, `sig_30`).
  - This is an **evidence / data feed limitation**, not an unresolved strategy choice requiring Samarth's approval.

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
- Implement the **Multi-Timeframe Confirmation Monitor** split strictly into two decoupled responsibilities:
  1. **Continuous Confirmation Engine Processing**:
     - Accepted lower-timeframe confirmation engines (`ChochDetector`, `ISSEngine`) process their independently configured candle history continuously from their established start candles.
     - They do **NOT** pause, reset, or restart detection when a physical tap occurs, preserving patterns that begin before activation touch and complete afterward (`sig_06`).
  2. **Passive Event-to-Activation Matcher**:
     - Ingests newly completed, authoritative confirmation events emitted by the continuous confirmation engines.
     - Associates completed events with currently eligible activation generations (`PENDING_ACTIVATION` and `REARMED_PENDING` from `ActivationSessionCoordinator`).
     - Emits typed `CandidateSignalRecord`s with explicit `CandidateSetupKey`s.
  - **Strict Implementation Boundaries**:
     * The matcher must **NOT** restart pattern detection at the touch.
     * The matcher must **NOT** inherit start candles silently.
     * The matcher must **NOT** arbitrate competing winners.
     * The matcher must **NOT** consume physical levels in the usage ledger.
     * The matcher must **NOT** publish final signals.
- Candidate arbitration, atomic transaction commits, and scoped usage ledger follow in Milestone 32.
