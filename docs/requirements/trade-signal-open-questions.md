# Trade-Signal Open Strategy Questions & Reconciliation Baseline — Milestone 30

**Milestone**: Milestone 30 — Trade-Signal Business Logic Requirements and Acceptance Contract  
**Target Decision-Maker**: Samarth  
**Status**: Pending Formal Strategy Reconciliation  

> [!IMPORTANT]
> **Purpose**:
> This document catalogs only **consequential unresolved strategy decisions** that affect the trade-signal pipeline (confirmation matching, candidate selection, signal publication, and level usage).
> Per `AGENTS.md` and Perplexity directives, autonomous development **never invents missing trading rules or default resolutions**. Unresolved items operate strictly under fail-closed policies until Samarth formally reconciles them.

---

## 1. Consequential Open Questions for Samarth

### Question 1: CHOCH Boundary Condition ($c_1 == p_2$) Under Pending Activation
- **Source Conflict / Ambiguity**:
  - `Choch.pdf` (§1, Rule 2) requires the candle close to strictly breach Point 2 ($c_1 > p_2$ for bullish, $c_1 < p_2$ for bearish).
  - In edge cases where a candle closes exactly equal to Point 2 ($c_1 == p_2$), existing engine behavior halts authoritative updates and freezes state.
- **Affected Signal Behavior**:
  - If a source timeframe (e.g. H4) is currently in `PENDING_ACTIVATION` and its underlying MSM/CHOCH coordinator encounters a $c_1 == p_2$ boundary equality, should the pending activation:
    1. Freeze in place (fail-closed, awaiting resolution before any signal can confirm)?
    2. Cancel immediately as structurally suspect?
    3. Continue evaluating confirmations from previously established structural levels?
- **Current Fail-Closed Specification in Milestone 30**:
  - **Option 1 (Freeze fail-closed)**: Confirmation evaluation for that source timeframe is immediately frozen (`BLOCKED_SOURCE_UNRESOLVED`); no trade signal is published.
- **Minimal Decision for Samarth**:
  - *Confirm whether $c_1 == p_2$ at the source level freezes pending activations fail-closed or immediately invalidates them.*

---

### Question 2: ISS Multi-Candle Pullback Qualification as LTF Confirmation
- **Source Conflict / Ambiguity**:
  - `ISS.pdf` defines the 5-point structural shift. Standard fixtures verify single-candle pullbacks.
  - Multi-candle pullbacks during ISS formation on lower timeframes (H1, M5, M1) introduce ambiguous boundary definitions that remain unreconciled in strategy documentation.
- **Affected Signal Behavior**:
  - When an activated TJL level seeks confirmation on its lower timeframe, does a candidate ISS pattern with a multi-candle pullback qualify as a valid confirmation pattern, or must confirmation strictly require single-candle pullback ISS formations?
- **Current Fail-Closed Specification in Milestone 30**:
  - **Strict single-candle pullback only**: Candidate ISS confirmations with multi-candle pullbacks are marked `UNRESOLVED_CONFIRMATION_GAP` and emit no trade signals.
- **Minimal Decision for Samarth**:
  - *Confirm whether multi-candle pullback ISS patterns are eligible for entry confirmation, or if confirmation is strictly restricted to single-candle pullback ISS patterns.*

---

### Question 3: Intra-Candle Event Sequencing (Tap vs. Confirmation on Same Coarse Bar)
- **Source Conflict / Ambiguity**:
  - `MTF-Analysis.pdf` §7 (Q&A 12) states: *"The tap candle may also confirm entry. Enter at that close if it confirms a valid directional pattern."*
  - `OPEN-04` (`docs/requirements/approved-clarifications.md`) states: *"If the intra-bar sequence of events cannot be determined from available data, mark as UNKNOWN_ORDER; do not emit a speculative trade signal."*
  - On coarse candle data (e.g. H4 tap where confirmation pattern completes on the same coarse H4 window), the exact temporal sequence (did the tap happen before or after the confirmation pattern started/completed?) cannot always be proven from OHLC bars alone.
- **Affected Signal Behavior**:
  - If sub-bar tick or lower-timeframe data is missing, should a setup where tap and confirmation fall within the same coarse bar be rejected as `UNKNOWN_ORDER`, or may the confirmation be accepted if the confirming candle's close timestamp is $\ge$ the tap candle's open timestamp?
- **Current Fail-Closed Specification in Milestone 30**:
  - **Strict causality**: If the sequence cannot be established definitively from available timestamps, mark `UNKNOWN_ORDER` and suppress signal publication.
- **Minimal Decision for Samarth**:
  - *Confirm whether intra-bar ordering requires sub-timeframe (e.g. M1) timestamp evidence to prove the tap occurred prior to confirmation completion.*

---

## 2. Summary of Fail-Closed Policies Maintained

Until Samarth provides explicit, approved resolutions to the questions above, the trade-signal requirements contract strictly enforces:
1. **Zero Guessing**: No defaults or speculative rules are assumed.
2. **Fail-Closed Gate**: Unresolved conditions suppress signal emission (`NO_SIGNAL`).
3. **Audit Trail**: Every suppressed candidate records an explicit diagnostic flag (`BLOCKED_SOURCE_UNRESOLVED`, `UNRESOLVED_CONFIRMATION_GAP`, or `UNKNOWN_ORDER`).
