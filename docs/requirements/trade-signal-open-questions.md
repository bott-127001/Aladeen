# Trade-Signal Open Strategy Questions & Reconciliation Baseline — Milestone 30

**Milestone**: Milestone 30 — Trade-Signal Business Logic Requirements and Acceptance Contract  
**Target Decision-Maker**: Samarth  
**Status**: Pending Formal Strategy Reconciliation  

> [!IMPORTANT]
> **Purpose & Authority Boundary**:
> This document catalogs only **consequential unresolved strategy decisions** that affect the trade-signal pipeline (confirmation matching, candidate selection, signal publication, and level usage).
> Per `AGENTS.md` and Perplexity directives, autonomous development **never invents missing trading rules or default resolutions**. Unresolved items operate strictly under fail-closed policies until Samarth formally reconciles them.
> Note: Document references below are preserved from strategy transcription notes; direct PDF page inspection is unverified in this phase.

---

## 1. Consequential Open Questions for Samarth

### Question 1: CHOCH Boundary Condition ($c_1 == p_2$) Under Pending Activation
- **Source Conflict / Ambiguity**:
  - Strategy transcription notes (`Choch.pdf` §1) record that a candle close breaching Point 2 ($c_1 > p_2$ for bullish, $c_1 < p_2$ for bearish) identifies a CHOCH.
  - In edge cases where a candle closes exactly equal to Point 2 ($c_1 == p_2$), the existing accepted engine halts authoritative progress and freezes state.
- **Affected Signal Behavior**:
  - If a source timeframe (e.g. H4) is currently in `PENDING_ACTIVATION` and its underlying MSM/CHOCH coordinator encounters a $c_1 == p_2$ boundary equality, should the pending activation:
    1. Freeze in place fail-closed (`BLOCKED_SOURCE_UNRESOLVED`, awaiting resolution before any signal can confirm)?
    2. Cancel immediately as structurally suspect?
    3. Continue evaluating confirmations from previously established structural levels?
- **Current Fail-Closed Specification in Milestone 30**:
  - **Option 1 (Freeze fail-closed)**: Confirmation evaluation for that source timeframe is immediately frozen (`BLOCKED_SOURCE_UNRESOLVED`); no trade signal is published.
- **Minimal Decision for Samarth**:
  - *Confirm whether $c_1 == p_2$ at the source level freezes pending activations fail-closed or immediately invalidates them.*

---

### Question 2: ISS Multi-Candle Pullback Qualification as LTF Confirmation
- **Source Conflict / Ambiguity**:
  - `MTF-Analysis.pdf` §6 requires applying existing approved normal CHOCH and ISS detection rules unchanged on assigned confirmation timeframes.
  - In strategy transcription notes, standard verified ISS fixtures depict single-candle pullbacks. Multi-candle pullbacks during ISS formation introduce ambiguous intermediate structural points and boundary conditions that remain formally unreconciled in strategy documentation.
- **Affected Signal Behavior**:
  - Does an ISS pattern with an unverified multi-candle pullback constitute an authoritative confirmed directional ISS event eligible for entry confirmation, or is confirmation restricted strictly to reconciled, unambiguous ISS formations?
- **Current Fail-Closed Specification in Milestone 30**:
  - **Fail-closed blocking**: Candidate ISS confirmations with unreconciled multi-candle pullbacks are marked `BLOCKED_UNRESOLVED_CONFIRMATION_GAP` and emit no trade signals. Only authoritative confirmed ISS events without ambiguous pullback paths qualify.
- **Minimal Decision for Samarth**:
  - *Formally reconcile whether multi-candle pullback ISS patterns qualify as valid entry confirmation, or define the exact boundary criteria for multi-candle pullback ISS formations.*

---

### Question 3: Intra-Candle Ordering Limitation on Coarse Feeds
- **Source Evidence Contract (`OPEN-04`, `OPEN-06`)**:
  - `MTF-Analysis.pdf` §7 (Q&A 12) allows the tap candle to confirm entry if it completes a valid pattern.
  - `OPEN-04` requires that events on half-open candle intervals `[open_time, close_time)` establish their intra-bar order authoritatively; if order cannot be determined from available data, it must mark `UNKNOWN_ORDER` and suppress signals.
  - `OPEN-06` requires actual physical price print observations and forbids geometric path interpolation.
  - On coarse data feeds where sub-bar sequence timestamps are unavailable, a coarse bar containing both a price print inside the zone and a confirmation pattern completion cannot authoritatively prove whether the tap preceded pattern completion.
- **Affected Signal Behavior**:
  - This is documented strictly as a **data feed evidence limitation**, not an invented strategy rule. When sub-bar print timestamps are absent and monotonic sequence indexing cannot establish order, coarse same-candle tap and confirmation fail closed as `UNKNOWN_ORDER`.
- **Minimal Decision for Samarth**:
  - *Acknowledge that coarse data feeds lacking sub-bar sequence evidence suppress same-candle tap/confirmation signals fail-closed (`UNKNOWN_ORDER`).*

---

## 2. Summary of Fail-Closed Policies Maintained

Until Samarth provides explicit, approved resolutions to the questions above, the trade-signal requirements contract strictly enforces:
1. **Zero Guessing**: No defaults or speculative rules are assumed.
2. **Fail-Closed Gate**: Unresolved conditions suppress signal emission (`NO_SIGNAL`).
3. **Audit Trail**: Every suppressed candidate records an explicit diagnostic flag (`BLOCKED_SOURCE_UNRESOLVED`, `BLOCKED_UNRESOLVED_CONFIRMATION_GAP`, or `UNKNOWN_ORDER`).
