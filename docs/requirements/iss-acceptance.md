# Internal Structure Shift (ISS) — Acceptance Specification

Last Updated: 2026-11-05

> [!IMPORTANT]
> **Specification Authority & Provenance**:
> - **Primary Source**: `docs/strategy/ISS.pdf` (Version 1 — Final agreed rules, 13 October 2026, 11:16 PM IST).
> - **Transcription Aid**: [`docs/strategy/extracted/iss.md`](../strategy/extracted/iss.md).
> - **Ancestry**: References to `TopG.pdf` (pages 15–16) represent ancestry stated by the available strategy source rather than an independently inspected primary document.
> - **Prerequisite Specifications**: Inherits and reuses Market Structure Marking rules from `docs/strategy/Market Structure Marking.docx` and [`docs/requirements/msm-acceptance.md`](msm-acceptance.md), and CHOCH rules from `docs/strategy/Choch.pdf` and [`docs/requirements/choch-acceptance.md`](choch-acceptance.md).
> - **Approved Clarifications**: Governed by [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (OPEN-01, OPEN-03, OPEN-04, OPEN-07, OPEN-08, OPEN-09, OPEN-10).
> - **Strict Safety & Scope Boundary**: Pure read-only market-structure phase. Strictly **zero trade entries, zero order execution, zero position gating, and zero profitability claims**.

---

## 1. Scope and Authority

Internal Structure Shift (ISS) is a secondary structural pattern operating within an active primary (main) market structure cycle on the H1 timeframe.
- **Main marking stays active throughout**: ISS alone never changes or reverses the main marking direction.
- **Distinct from Main CHOCH**: Main CHOCH retains its own confirmation rules (2 consecutive closes beyond last support/resistance). ISS is intended as an early structural shift signal before main CHOCH occurs; a main support/resistance break is **not** an ISS prerequisite.
- **Exclusions**: Engulfing retracement (TopG page 13) and dual CHOCH (TopG page 14) are excluded from the algorithm per the primary source specification.
- **No Execution / Profitability**: This specification defines detection, marking, boundaries, zone geometry, and search lifecycle only.

---

## 2. Main and Internal Numbering & Prerequisites

### 2.1 Main Structure Context
An ISS candidate requires an active main cycle with two captured boundary levels established through valid Market Structure Marking:
1. **Main Level 2**:
   - In **Bullish** main structure: The latest confirmed swing low (`CL`, last support) established by a completed confirmed MSM pair.
   - In **Bearish** main structure: The latest confirmed swing high (`CH`, last resistance) established by a completed confirmed MSM pair.
   - *Provenance Requirement*: Selecting an initial start candle does not automatically make it a confirmed structural level. Main level 2 must be established through actual completed pair confirmation before level 3 is captured.
2. **Main Level 3**:
   - In **Bullish** main structure: The active tentative swing high (`tentative_high`).
   - In **Bearish** main structure: The active tentative swing low (`tentative_low`).
   - Identified at the close of the second candle ($p_2$) of the valid 2-candle main pullback.
   - Its original candle serves as the **internal search reference**, not an ISS zone candle.

### 2.2 Boundary Capture & Freezing
- When valid main pullback candle $p_2$ completes and identifies active main level 3, the engine captures:
  - Main Level 2: body-edge price and original candle identity.
  - Main Level 3: body-edge price and original candle identity.
- **Freezing Rule**: These two boundary prices are permanently frozen for the lifetime of that ISS candidate. Later price extremes do **not** move or stretch them.
- **Allowed Range**: The inclusive price interval:
  $$\text{Allowed Range} = [\min(P_{\text{main\_2}}, P_{\text{main\_3}}),\, \max(P_{\text{main\_2}}, P_{\text{main\_3}})]$$

### 2.3 First Internal Pullback Timing Restriction
- **Chronological Forward Scan Boundary**: Both candles of the first internal pullback must occur at chronological positions strictly after the completion of the second candle ($p_2$) of the main pullback that identified main level 3:
  $$\text{chronological\_position}(\text{internal\_p1}) > \text{chronological\_position}(p_2)$$
  $$\text{chronological\_position}(\text{internal\_p2}) > \text{chronological\_position}(\text{internal\_p1}) > \text{chronological\_position}(p_2)$$
- Neither main pullback candle ($p_1, p_2$) may be reused as part of the first internal pullback pair.
- The internal tentative level search window, however, looks back to the main level 3 reference candle (inclusive) through the candle before the internal pullback pair.

---

## 3. Internal Five-Point Structure

"Five waves" in the strategy documents strictly means **five internal marked structural points**—specifically two confirmed swing pairs plus the next tentative point. It does **not** mean five arbitrary price legs or Elliott wave heuristics.

Internal marking runs in the **opposite direction** of the prevailing main marking:
- **Bearish Main Structure $\implies$ Internal UPWARD Marking**:
  - Point 1: `CH1` (Confirmed High 1)
  - Point 2: `CL1` (Confirmed Low 1)
  - Point 3: `CH2` (Confirmed High 2)
  - Point 4: `CL2` (Confirmed Low 2)
  - Point 5: `Tentative High` (identified by 3rd internal pullback; does NOT require a continuation break)
- **Bullish Main Structure $\implies$ Internal DOWNWARD Marking**:
  - Point 1: `CL1` (Confirmed Low 1)
  - Point 2: `CH1` (Confirmed High 1)
  - Point 3: `CL2` (Confirmed Low 2)
  - Point 4: `CH2` (Confirmed High 2)
  - Point 5: `Tentative Low` (identified by 3rd internal pullback; does NOT require a continuation break)

### 3.1 Inherited Market-Structure Rules
The internal state machine strictly reuses the approved Market Structure Marking rules:
1. **Pullbacks**:
   - Upward internal: 2 consecutive red candles, second closing strictly below first candle's bottom wick tip (`close < low[first]`).
   - Downward internal: 2 consecutive green candles, second closing strictly above first candle's top wick tip (`close > high[first]`).
   - Flat candles interrupt required-color pairs but remain eligible for searches and breaks.
2. **Tentative Level Selection**:
   - Upward: Highest upper body edge (`UB = max(open, close)`) from search reference through candle before pullback pair, excluding both pullback candles. If tied, select latest candle.
   - Downward: Lowest lower body edge (`LB = min(open, close)`) from search reference through candle before pullback pair, excluding both pullback candles. If tied, select latest candle.
3. **Confirmation & Opposite Level**:
   - Upward high confirmation: Closing strictly above tentative high (`close > tentative_high.price`). Confirms high and opposite low (lowest `LB` from high's candle through break candle, including both endpoints; latest if tied). Confirmed low becomes next reference.
   - Downward low confirmation: Closing strictly below tentative low (`close < tentative_low.price`). Confirms low and opposite high (highest `UB` from low's candle through break candle, including both endpoints; latest if tied). Confirmed high becomes next reference.
4. **Strict Comparisons vs. Boundary Equality**:
   - All internal MSM pullback and continuation comparisons use strict inequalities (`>`, `<`).
   - Equality is permitted **only** in the ISS boundary evaluation.

---

## 4. Boundary Validation & Confirmation Conditions

### 4.1 Boundary Evaluation
For an ISS pattern to confirm, every one of the five marked internal points must lie within the frozen inclusive boundary:
$$\min(P_{\text{main\_2}}, P_{\text{main\_3}}) \le P_{\text{internal\_pt\_k}} \le \max(P_{\text{main\_2}}, P_{\text{main\_3}}) \quad \forall k \in \{1, 2, 3, 4, 5\}$$

- **Inclusive Equality**: Exact equality ($P_{\text{internal}} == P_{\text{boundary}}$) is valid and satisfies the boundary condition.
- **Body Edges Only**: The boundary test evaluates the marked body-edge price ($UB$ or $LB$) of the selected extreme point, **not** every intervening candle.
- **Wick-Only Excursions Permitted**: A candle having wicks extending beyond the boundaries does not invalidate an otherwise valid marked level whose body edge remains inside.
- **Original Zone Wicks**: The original candle's wick can extend outside the range without invalidating an otherwise eligible body-edge level.

### 4.2 Exact Confirmation Timing
- **Confirmation Candle**: ISS confirms at the exact close of the second candle ($ip_2$) of the valid internal pullback that identifies the **fifth internal point** (tentative high for bearish main, tentative low for bullish main).
- **No Continuation Break Required**: Do **not** wait for a continuation break confirming that fifth point.
- **Completion Close Boundary Condition**:
  The completion candle ($ip_2$) itself must close **inside** the inclusive range:
  $$\min(P_{\text{main\_2}}, P_{\text{main\_3}}) \le \text{close}(ip_2) \le \max(P_{\text{main\_2}}, P_{\text{main\_3}})$$
  If the fifth marked point is inside the boundary but $ip_2$ closes outside the boundary, ISS is **NOT** confirmed.

---

## 5. Distinct Search Lifecycles

An ISS search candidate transitions through strictly separated, non-overlapping lifecycles:

```
                            [Main Level 3 Identified & Boundaries Frozen]
                                                  │
                                                  ▼
                                       [Internal Marking Active]
                                                  │
               ┌─────────────────────────┬────────┴────────────────┬────────────────────────┐
               ▼                         ▼                         ▼                        ▼
      [Out-of-Bounds Pt]       [Outside-Range Close]      [Main Continuation]         [Main CHOCH]
               │                         │                         │                        │
               ▼                         ▼                         ▼                        ▼
       PERMANENT REJECT            TRACKING ONLY                CANCEL                   CANCEL
    - Delete markings           - Retain markings          - Cancel candidate       - Cancel candidate
    - Stop marking              - Continue for tracking    - Confirm main level     - Retain history
    - Never revive              - Never confirm ISS        - Normal main proceeds   - New main direction
                                - Never revive
                                         │
               ┌─────────────────────────┘
               ▼
      [5 Points Valid & Completion Close Inside]
               │
               ▼
         CONFIRMED ISS
    - Create Point 3 & Point 4 Zones
    - Stop search for this Main Level 3
    - Retain in confirmed history
```

### 5.1 Lifecycle A: Confirmed ISS
- **Condition**: All 5 marked internal points are inside the frozen boundary, and the completion candle closes inside the boundary.
- **Action**:
  - One confirmed ISS signal per main level 3.
  - Construct the two structural zones (from internal points 3 and 4).
  - Stop the internal search for that main level 3.
  - Retain the confirmed ISS and its zones in immutable history.

### 5.2 Lifecycle B: Out-of-Bounds Marked Point (Permanent Rejection)
- **Condition**: Any internal marked level ($k \in \{1, 2, 3, 4, 5\}$) falls outside the fixed range ($P_k < \min$ or $P_k > \max$).
- **Action**:
  - Permanently reject ISS eligibility for that main level 3.
  - Remove that candidate's internal markings from the active state.
  - Stop its internal marking process immediately.
  - Create zero ISS zones.
  - Do **not** use the tracking-only exception to preserve its markings.
  - Never revive or restart that candidate under the same main level 3.
  - Shift to monitoring main CHOCH while keeping normal main marking active.

### 5.3 Lifecycle C: Valid Marked Prices with Outside-Range Completion Close (Tracking-Only)
- **Condition**: All 5 internal marked levels are inside the inclusive boundary, but the completion candle ($ip_2$) closes outside the boundary ($\text{close} < \min$ or $\text{close} > \max$).
- **Action**:
  - Do **not** confirm ISS. Create zero ISS zones.
  - Permanently lose ISS eligibility for this candidate under this main level 3.
  - Retain and continue internal level marking **ONLY for tracking** while awaiting main CHOCH.
  - A later internal sequence cannot revive ISS eligibility for this same main level 3.

### 5.4 Lifecycle D: Main Continuation Before ISS Completion
- **Condition**: A main continuation closing break confirms main tentative level 3 before ISS completes.
- **Action**:
  - Cancel the unfinished ISS candidate without creating ISS zones.
  - Normal main marking confirms its tentative level and opposite level and proceeds.
  - Await a new valid main tentative level 3 to start a fresh ISS search.

### 5.5 Lifecycle E: Main CHOCH Confirms
- **Condition**: Main CHOCH confirms (2 consecutive completed closes beyond main last support/resistance).
- **Action**:
  - Cancel any unfinished ISS candidate or tracking-only process.
  - Retain previously confirmed ISS zones and history (they are immutable).
  - Apply approved main CHOCH zone and restart rules. A fresh ISS search in the new direction requires a new valid main tentative level 3.

### 5.6 Lifecycle F: New Valid Main Level 3 (Fresh Search)
- **Condition**: Normal main marking identifies a new valid tentative level 3 (e.g. after a continuation break or while awaiting main CHOCH).
- **Action**:
  - Start a completely fresh ISS search with the new level 3's original candle as search reference.
  - Capture and freeze the current main level 2 and new main level 3 as fresh boundaries.
  - Require a fresh internal pullback pair strictly after the new main pullback.
  - Never revive a previously rejected candidate.

---

## 6. Original-Candle Zones: Geometry and Roles

ISS produces exactly **two zones** upon confirmation, derived strictly from internal points 3 and 4:
- **ISS Level 3** = **THIRD** internal marked point.
- **ISS Level 4 / A+** = **FOURTH** internal marked point.
- Neither zone is supplied by main level 3 or by the fifth internal tentative point!

### 6.1 Roles by Main Direction
| Main Direction | Internal Direction | Internal Point 3 | Zone Role | Internal Point 4 | Zone Role |
|:---|:---|:---|:---|:---|:---|
| **Bearish** | Upward | `CH2` (Confirmed High 2) | **RBS** (Resistance Becomes Support) | `CL2` (Confirmed Low 2) | **buying A+** |
| **Bullish** | Downward | `CL2` (Confirmed Low 2) | **SBR** (Support Becomes Resistance) | `CH2` (Confirmed High 2) | **selling A+** |

*Note on Terminology*: RBS = Resistance Becomes Support; SBR = Support Becomes Resistance. The "A+" designation is retained as taught by the strategy source; no additional filter or justification is approved.

### 6.2 Zone Construction from Original Candles
Zones are constructed strictly from the **original candle** that established the respective internal marked point:
- **High-Side Zones** (`RBS` in Bearish Main, `selling A+` in Bullish Main):
  - Lower edge: Upper Body Edge $UB = \max(\text{open}, \text{close})$
  - Upper edge: Top Wick Tip $\text{high}$
  - Interval: $[UB, \text{high}]$
- **Low-Side Zones** (`buying A+` in Bearish Main, `SBR` in Bullish Main):
  - Lower edge: Bottom Wick Tip $\text{low}$
  - Upper edge: Lower Body Edge $LB = \min(\text{open}, \text{close})$
  - Interval: $[\text{low}, LB]$
- **Zero-Wick Single Price Line**:
  - If the original candle has zero relevant wick (e.g. $\text{high} == UB$ on high-side, or $\text{low} == LB$ on low-side), the zone retains a thickness of zero ($[\text{price}, \text{price}]$) and is drawn as a single horizontal line.
  - Never artificially widen or substitute another candle.
- **Zone Wick Boundary Independence**:
  - While the marked body-edge price must lie within the frozen boundary range, the zone wick boundary may extend outside the captured range without invalidating the zone.

---

## 7. Event Ordering & Ambiguity Analysis (Without Priority Invention)

The primary ISS source (`docs/strategy/ISS.pdf` Section 11) explicitly addresses event ordering:
> *"No separate same-candle ISS/main-CHOCH priority rule is included. The user rejected that proposal and approved the completion-close boundary requirement to keep their confirmation conditions distinct."*

### 7.1 Scenario 1: Main Continuation on ISS Completion Candle
- If the would-be ISS completion candle closes beyond main level 3 in the continuation direction, it closes **outside** the frozen boundary range.
- **Source Result**: By Section 6 & 11, do **not** confirm ISS. Keep normal main marking active and apply its continuation rule.

### 7.2 Scenario 2: Outside-Range Completion Close vs. Main CHOCH
- If the ISS completion candle closes outside the boundary in the direction of main CHOCH:
  - ISS fails the completion-close boundary condition $\implies$ No ISS confirmed.
  - The close alone is not a confirmed main CHOCH (main CHOCH requires two consecutive closes strictly beyond last support/resistance under its own timing and point-3 prerequisites).
  - Main marking continues, and the engine monitors main CHOCH.

### 7.3 Scenario 3: Shared Close Between Main CHOCH and ISS Completion
- If a candle close simultaneously meets the closing criteria for main CHOCH confirmation (the second consecutive completed close beyond main last support/resistance) and would-be ISS completion:
  - By structural definition, Main Level 2 is the prevailing structural anchor (last support in bullish structure, or last resistance in bearish structure).
  - Main CHOCH requires closing strictly beyond this anchor level ({\text{main\_2}}$).
  - Because the frozen boundary range $[P_{\text{main\_2}}, P_{\text{main\_3}}]$ has {\text{main\_2}}$ as one of its defining endpoints, any completed close strictly beyond {\text{main\_2}}$ lies strictly **outside** the inclusive boundary.
  - Therefore, by the completion-close boundary condition (Section 4.2), that candle fails ISS completion.
  - This consequence follows directly from the boundary rule without inventing a separate intra-bar priority heuristic.
- **Isolated Limitation Preserved**: The separate unresolved interpretation regarding whether candle $'s close can simultaneously establish Point 3 and count as the first CHOCH candidate close $ remains an isolated dependency limitation.

---

## 8. Verifiable Acceptance Criteria

| ID | Category | Requirement | Verifiable Criterion |
|:---|:---|:---|:---|
| **AC-ISS-01** | Bearish Main Confirmation | Bearish main, 5 internal upward points inside boundary, completion close inside | ISS confirmed at $ip_2$ close; RBS zone on `CH2`, buying A+ zone on `CL2`. |
| **AC-ISS-02** | Bullish Main Confirmation | Bullish main, 5 internal downward points inside boundary, completion close inside | ISS confirmed at $ip_2$ close; SBR zone on `CL2`, selling A+ zone on `CH2`. |
| **AC-ISS-03** | Boundary Equality | Marked point exactly equals captured boundary price | $P_k == \text{boundary}$ is valid; does not reject ISS. |
| **AC-ISS-04** | Wick Excursions Allowed | Intervening or zone wicks pierce boundary while body edges remain inside | ISS remains valid; wick excursion does not reject. |
| **AC-ISS-05** | Out-of-Bounds Rejection | Any marked body edge lies strictly outside boundary | Candidate permanently rejected; internal markings deleted; stops marking. |
| **AC-ISS-06** | Outside-Range Completion | Marked points valid, but completion candle closes outside boundary | No ISS confirmed; no zones; internal markings retained ONLY for tracking. |
| **AC-ISS-07** | No Revival Same Level 3 | Sequence after rejected or outside-range candidate under same main level 3 | Cannot revive or confirm ISS under the same main level 3. |
| **AC-ISS-08** | Fresh Search New Level 3 | Normal main marking identifies fresh main level 3 | Fresh candidate opened with new frozen boundaries; requires new pullbacks. |
| **AC-ISS-09** | Main Continuation Cancel | Main continuation break confirms level 3 before ISS completes | Unfinished ISS candidate cancelled; normal main marking proceeds. |
| **AC-ISS-10** | Main CHOCH Cancellation | Main CHOCH confirms before ISS completes | Unfinished search/tracking cancelled; confirmed ISS history preserved. |
| **AC-ISS-11** | History Retention | Later main level confirmation or main CHOCH occurs | Previously confirmed ISS zones and labels retained immutably. |
| **AC-ISS-12** | Zone Point Provenance | Zones built from internal points 3 and 4 | Point 3 $\implies$ RBS/SBR, Point 4 $\implies$ A+; never from main 3 or internal 5. |
| **AC-ISS-13** | Zero-Wick Line Zones | Original candle has zero relevant wick | Zone has thickness 0 ($[P, P]$); drawn as labeled single price line. |
| **AC-ISS-14** | First Pullback Timing | First internal pullback candles | Both must occur strictly after second candle of main pullback ($p_2$). |
| **AC-ISS-15** | Prefix Replay Consistency | Replaying candle series with arbitrary unique candle IDs | Produces identical deterministic points, boundaries, and zones. |
