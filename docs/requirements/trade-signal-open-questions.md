# Trade-Signal Open Strategy Questions & Technical Evidence Baseline — Milestone 30

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

## 2. Technical Evidence Limitations (Non-Strategy Invariants)

The following item is documented strictly as a **data feed and observation evidence limitation**, not an unresolved strategy choice:

### Missing Authoritative Touch or Ordering Evidence
- **Evidence Contract (`OPEN-04`, `OPEN-06`, `MTF-Analysis.pdf` §7)**:
  - `MTF-Analysis.pdf` §7 (Q&A 12) permits the tap candle to confirm entry if it completes a valid pattern.
  - Where sub-bar tick/print timestamps are available, causal ordering is established directly ($t_{tap} < t_{close}$, Case A).
  - Where sub-bar timestamps are absent but discrete monotonic sequence indexing is available, causal order is established authoritatively ($seq_{tap} < seq_{conf}$, Case B).
  - Where neither sub-bar timestamps nor sequence ordering evidence are present on a shared coarse candle interval, the transition fails closed as `UNKNOWN_ORDER` (Case C).
- **Resolution**:
  - Missing authoritative touch or ordering evidence blocks the affected transition. Timestamp precision alone does not determine eligibility.
  - This is an **evidence/data stream limitation governed by causal physics**, not an unresolved strategy choice requiring Samarth's approval.

---

## 3. Summary of Fail-Closed Policies Maintained

Until Samarth provides explicit, approved resolutions to Questions 1 and 2, the trade-signal requirements contract strictly enforces:
1. **Zero Guessing**: No defaults or speculative rules are assumed.
2. **Fail-Closed Gate**: Unresolved conditions suppress signal emission (`NO_SIGNAL`).
3. **Audit Trail**: Every suppressed candidate records an explicit diagnostic flag (`BLOCKED_SOURCE_UNRESOLVED`, `BLOCKED_UNRESOLVED_CONFIRMATION_GAP`, or `UNKNOWN_ORDER`).
