# Change of Character (CHOCH) — Acceptance Specification

Last Updated: 2026-11-05

> [!IMPORTANT]
> **Specification Authority & Provenance**:
> Derived directly from the original strategy document `docs/strategy/Choch.pdf` (with [`docs/strategy/extracted/choch.md`](../strategy/extracted/choch.md), Version 2, 13 October 2026, serving as a review transcription aid). Reference to `TopG.pdf` represents ancestry stated by the available strategy source rather than an independently inspected primary document. Original MSM algorithms are drawn from `Market Structure Marking.docx` Section 3 (Upward Algorithm) and Section 4 (Downward Algorithm), distinct from subsection numbering introduced by local acceptance specifications. Approved clarifications are governed by [`docs/requirements/approved-clarifications.md`](approved-clarifications.md) (OPEN-01, OPEN-03, OPEN-04, OPEN-08, OPEN-09, OPEN-10).
> Operates alongside the Market Structure Marking (MSM) engine as a strict read-only structural transition module.
> **Strict Non-Invention & Safety Boundary**: Pure structure phase. Strictly **zero trade entries, zero automated execution, zero position gating, and zero profitability claims**.

---

## 1. Scope & Strategy Integration Boundary

CHOCH represents a structural reversal transition from an active Market Structure Marking cycle. It monitors completed candles for a definitive failure of the prevailing trend's structural anchor (the last confirmed support in upward structure, or the last confirmed resistance in downward structure).

```
Prevailing MSM Cycle (Upward)                      CHOCH Transition                       New MSM Cycle (Downward)
─────────────────────────────                      ────────────────                       ────────────────────────
Confirmed Low (Last Support) ────────┐
                                     ▼
Active Tentative Point 3 ──────► [Evaluate Closes] ──► [2 Strict Closes Below Support] ──► Old Cycle Terminates
                                     ▲                                                 3 Zones Formed
                                     │                                                 Restart from Point 3 Original Candle
                                 Candidate Pair                                        (Pullback must be strictly after)
```

### 1.1 Input Dependencies from MSM
A CHOCH evaluation requires verified state from the underlying MSM state machine:
1. **Active Marking Direction**: `UPWARD` or `DOWNWARD`.
2. **Structural Comparison Level**:
   - For `UPWARD` marking: **Last Support** (the latest confirmed swing low's lower body edge `LB`).
   - For `DOWNWARD` marking: **Last Resistance** (the latest confirmed swing high's upper body edge `UB`).
   - *Rule*: Tentative levels do NOT replace confirmed levels.
3. **Active Tentative Point 3**:
   - The active tentative extreme maintained by the unfinished MSM cycle (`tentative_high` in upward marking, or `tentative_low` in downward marking).
   - Point 3 is identified at the close of the second candle (`p2`) of the valid 2-candle pullback in the MSM cycle.

---

## 2. Candle Measurements & Strict Inequality Principle

### 2.1 Body Edges vs. Comparison Prices
- **Upper Body Edge**: `UB(i) = max(open[i], close[i])`
- **Lower Body Edge**: `LB(i) = min(open[i], close[i])`
- **Top Wick Tip**: `high[i]`
- **Bottom Wick Tip**: `low[i]`

The structural comparison price is strictly the body-edge price established by the marking module:
- Upward Last Support price = `last_support.price = LB(last_support.candle_idx)`.
- Downward Last Resistance price = `last_resistance.price = UB(last_resistance.candle_idx)`.
Zone wick boundaries do NOT substitute for these comparison prices.

### 2.2 Strict Inequality (Equality & Wick Rejection)
In all CHOCH comparisons, equality never qualifies:
- **Bearish Comparison**: `close < last_support.price` (strictly below).
  - An exact touch (`close == last_support.price`) **FAILS**.
  - A wick crossing (`low < last_support.price` while `close >= last_support.price`) **FAILS**.
- **Bullish Comparison**: `close > last_resistance.price` (strictly above).
  - An exact touch (`close == last_resistance.price`) **FAILS**.
  - A wick crossing (`high > last_resistance.price` while `close <= last_resistance.price`) **FAILS**.

### 2.3 Candle Color Independence
- The confirmation condition is strictly a **closing-price condition**, not a candle-color condition.
- Candle color (green, red, or flat) can never substitute for the required closing price.
- In Bearish CHOCH, both qualifying candles must close strictly below last support regardless of whether either candle is red, green, or flat.
- In Bullish CHOCH, both qualifying candles must close strictly above last resistance regardless of whether either candle is green, red, or flat.

---

## 3. Exact CHOCH Confirmation Conditions

### 3.1 Bearish CHOCH Confirmation
Occurs while marking `UPWARD` structure:
1. **Prerequisite**: An active tentative Point 3 (`tentative_high`) must already be identified.
2. **Consecutive Closes**: Two immediately adjacent, consecutive completed candles in the chronological series `(c1, c2)` (where `c2` is the immediate next chronological completed bar following `c1`, rather than an arithmetic operation on arbitrary source IDs) must both satisfy:
   - `close[c1] < last_support.price`
   - `close[c2] < last_support.price`
3. **Confirmation Timing**: Bearish CHOCH is confirmed at the exact close of the second candle (`c2`).
4. **Candidate Pair Failure**:
   - A single qualifying close (`close[c1] < last_support.price`) is NOT confirmed CHOCH.
   - If candle `c2` fails to close strictly below last support (i.e. `close[c2] >= last_support.price`), the pair `(c1, c2)` fails.
   - `c1` cannot be combined with any subsequent non-consecutive close. The engine must search for a completely new adjacent qualifying pair in chronological order.

### 3.2 Bullish CHOCH Confirmation
Occurs while marking `DOWNWARD` structure:
1. **Prerequisite**: An active tentative Point 3 (`tentative_low`) must already be identified.
2. **Consecutive Closes**: Two immediately adjacent, consecutive completed candles in the chronological series `(c1, c2)` (where `c2` is the immediate next chronological completed bar following `c1`, rather than an arithmetic operation on arbitrary source IDs) must both satisfy:
   - `close[c1] > last_resistance.price`
   - `close[c2] > last_resistance.price`
3. **Confirmation Timing**: Bullish CHOCH is confirmed at the exact close of the second candle (`c2`).
4. **Candidate Pair Failure**:
   - A single qualifying close (`close[c1] > last_resistance.price`) is NOT confirmed CHOCH.
   - If candle `c2` fails to close strictly above last resistance (i.e. `close[c2] <= last_resistance.price`), the pair `(c1, c2)` fails.
   - `c1` cannot be combined with any subsequent non-consecutive close. The engine must search for a completely new adjacent qualifying pair in chronological order.

---

## 4. Point 3 Eligibility, Timing & Lifecycle

### 4.1 Identification Timing & Same-Close Interpretation Boundary
- **Source Rule**: Point 3 must already be identified when the first qualifying CHOCH candle closes.
- **Strictly Ineligible Closes**: Any candle completing strictly *before* Point 3 identification (e.g. candle `p1` or earlier in the cycle) cannot count toward CHOCH confirmation.
- **Settled Later-Candle Case**: When the first qualifying close occurs on a candle strictly after Point 3 identification (chronological index $c_1 \ge p_2 + 1$), eligibility is established and fully authorized for implementation.
- **Narrowly Scoped Same-Close Question ($c_1 == p_2$)**:
  - Point 3 is identified upon the completed close of the second pullback candle `p2`.
  - If that same candle `p2` also closes strictly beyond Last Support (in upward marking) or Last Resistance (in downward marking), can `p2` simultaneously serve as the identification bar for Point 3 and count as the first qualifying CHOCH close `c1`?
  - **Status: UNRESOLVED PENDING SOURCE RECONCILIATION**.
  - Neither "count" nor "do not count" is mandated by the source text. In accordance with strict non-invention, this specific edge case is isolated as pending source clarification. Engines must not silently adopt either default, and test fixtures must not force a boolean outcome for $c_1 == p_2$.
- **Absence of Point 3**: If there is no active tentative Point 3 (e.g. no valid pullback has completed yet in the current cycle), CHOCH cannot be evaluated or confirmed; evaluation fails closed.

### 4.2 Point 3 Retention vs. Raw Extremes
- Point 3 is strictly the active tentative swing level identified by the formal MSM pullback mechanism.
- A subsequent candle that achieves a higher high (in upward structure) or lower low (in downward structure) without forming a new confirmed cycle does NOT displace or replace the active tentative Point 3.

### 4.3 Cycle Completion & Loss of Tentative Eligibility
- If price achieves a continuation closing break of the tentative level before a CHOCH sequence confirms:
  - In upward structure: `close[k] > tentative_high.price`.
  - In downward structure: `close[k] < tentative_low.price`.
- The tentative level immediately transitions to a **Confirmed Swing Point** (`CONFIRMED_HIGH` or `CONFIRMED_LOW`).
- Upon confirmation, that level loses its tentative status and is no longer an active Point 3.
- Any in-progress CHOCH close count resets. A new tentative Point 3 must be identified by a subsequent valid pullback before CHOCH can be evaluated.

---

## 5. Three Original-Candle Zones & Geometry

Upon confirmed CHOCH (at the close of `c2`), three structural zones are formed from the original candles of the structural swing points:

### 5.1 Directional Zone Roles

| Transition | Confirmed Low Original Candle | Confirmed High Original Candle | Active Tentative Point 3 Original Candle |
|:---|:---|:---|:---|
| **Bearish CHOCH** (from Upward) | **SBR** (Support Becomes Resistance) | **QML / A+** | **Double Top** |
| **Bullish CHOCH** (from Downward) | **QML / A+** | **RBS** (Resistance Becomes Support) | **Double Bottom** |

- **SBR**: Prior support level now expected to act as resistance.
- **RBS**: Prior resistance level now expected to act as support.
- **QML / A+**: Quasimodo Level / A+ zone formed from the major swing extreme of the broken trend.
- **Double Top / Bottom**: Zone formed from the tentative Point 3 original candle prior to the break.

### 5.2 Zone Geometry & Boundary Definitions
A zone's vertical boundaries are derived strictly from its original candle's body edge and wick tip:

1. **High-Side Zones** (Upper extreme boundary):
   - Confirmed High original candle
   - Bearish QML / A+
   - Bullish RBS
   - Double Top (Point 3 High)
   $$\text{Lower Boundary} = \text{Upper Body Edge} = \max(\text{open}, \text{close})$$
   $$\text{Upper Boundary} = \text{Top Wick Tip} = \text{high}$$
   $$\text{Zone Interval} = [\max(\text{open}, \text{close}),\ \text{high}]$$

2. **Low-Side Zones** (Lower extreme boundary):
   - Confirmed Low original candle
   - Bearish SBR
   - Bullish QML / A+
   - Double Bottom (Point 3 Low)
   $$\text{Lower Boundary} = \text{Bottom Wick Tip} = \text{low}$$
   $$\text{Upper Boundary} = \text{Lower Body Edge} = \min(\text{open}, \text{close})$$
   $$\text{Zone Interval} = [\text{low},\ \min(\text{open}, \text{close})]$$

### 5.3 Zero Relevant Wick Rule (Price-Line Preservation)
- If the original candle has no wick on the relevant side:
  - High-side candle where $\text{high} == \max(\text{open}, \text{close})$:
    $$\text{Upper Boundary} == \text{Lower Boundary} = \max(\text{open}, \text{close})$$
  - Low-side candle where $\text{low} == \min(\text{open}, \text{close})$:
    $$\text{Lower Boundary} == \text{Upper Boundary} = \min(\text{open}, \text{close})$$
- **Mandate**: Preserve the zone as a **single horizontal price line** with thickness 0.
- Do NOT artificially expand, pad, or widen the zone.
- Do NOT substitute an adjacent candle.

---

## 6. Old Cycle Termination & New-Direction Restart

At the close of qualifying candle `c2`:
1. **Terminate Old Unfinished Cycle**: The prevailing MSM cycle immediately ends. It no longer waits for a continuation break.
2. **Preserve Confirmed History**: All prior confirmed swing points and confirmed pairs remain immutable in history.
3. **Establish Zones**: The three zones are assigned their labels and bounds.
4. **New Marking Direction**:
   - Bearish CHOCH switches active marking direction to `DOWNWARD`.
   - Bullish CHOCH switches active marking direction to `UPWARD`.
5. **Restart Reference Candle**:
   - The original candle of Point 3 becomes the new search reference candle (`search_start`) for the new direction.
6. **Post-Confirmation Pullback Restriction**:
   - Both candles of the first valid pullback in the new direction `(p1_{new}, p2_{new})` must occur **strictly after** the confirmation candle `c2`:
     $$\text{idx}(p1_{new}) > \text{idx}(c2)$$
   - The confirmation candle `c2` CANNOT be reused as a pullback candle for the new direction.

---

## 7. Event Provenance & Timestamp Tracking

To uphold OPEN-04, OPEN-08, and OPEN-09, every CHOCH event records strict provenance:
- **`source_candle_time`**: Open timestamp of candle `c2` (`c2.time`).
- **`confirmed_at`**: Close timestamp of candle `c2` (`c2.close_time`).
- **`point3_id`**: Identifier of the tentative Point 3 swing record.
- **`point3_identified_at`**: Close timestamp of `p2` when Point 3 was identified.
- **`broken_level_price`**: Body-edge price of the broken support/resistance.
- **`broken_level_id`**: Identifier of the broken support/resistance swing record.
- **`status`**: `CONFIRMED`.
- **`zones`**: Dictionary mapping role (`SBR`/`RBS`, `QML_A_PLUS`, `DOUBLE_TOP`/`DOUBLE_BOTTOM`) to explicit geometry `{lower_price, upper_price, is_line, original_candle_time}`.

If the intra-bar event sequence cannot be determined, it must be marked `UNKNOWN_ORDER` (OPEN-04); no speculative assumptions are permitted.

---

## 8. Same-Bar Ambiguity Analysis (MSM Continuation vs. CHOCH)

### 8.1 Mathematical Non-Overlap of Same-Close Continuation vs. CHOCH
Can a single completed candle `k` simultaneously satisfy an MSM continuation break and a CHOCH break?

1. **Upward Marking Search Geometry**:
   - In `Market Structure Marking.docx` Section 3, the tentative-high search window begins at `search_start`, which is the confirmed-low reference candle (`last_support`).
   - The tentative-high search evaluates upper body edges $\text{UB}$ across this window, which includes `last_support` itself.
   - For any candle, $\text{UB} \ge \text{LB}$. Therefore, the maximum $\text{UB}$ over the search window is at least as large as the lower body edge of `last_support`:
     $$\text{tentative\_high.price} \ge \text{last\_support.price}$$
   - Non-strict level ordering $\text{tentative\_high} \ge \text{last\_support}$ holds unconditionally from the search geometry alone.
   - Equality $\text{tentative\_high} == \text{last\_support}$ is theoretically constructible if the search window contains only a flat candle (e.g. doji where $\text{open} == \text{close} \implies \text{UB} == \text{LB}$).
   - Break evaluation requires strict inequalities:
     - Upward continuation break requires: $\text{close}[k] > \text{tentative\_high.price}$.
     - Bearish CHOCH close requires: $\text{close}[k] < \text{last\_support.price}$.
   - Because $\text{tentative\_high.price} \ge \text{last\_support.price}$, a single scalar value $\text{close}[k]$ cannot simultaneously satisfy $\text{close}[k] > \text{tentative\_high.price}$ and $\text{close}[k] < \text{last\_support.price}$. (If it did, $\text{close}[k] > \text{tentative\_high} \ge \text{last\_support} > \text{close}[k] \implies \text{close}[k] > \text{close}[k]$, a mathematical impossibility).

2. **Downward Marking Search Geometry**:
   - In `Market Structure Marking.docx` Section 4, the tentative-low search window begins at `search_start`, which is the confirmed-high reference candle (`last_resistance`).
   - The tentative-low search evaluates lower body edges $\text{LB}$ across this window, which includes `last_resistance`.
   - For any candle, $\text{LB} \le \text{UB}$. Therefore:
     $$\text{tentative\_low.price} \le \text{last\_resistance.price}$$
   - Break conditions:
     - Downward continuation break requires: $\text{close}[k] < \text{tentative\_low.price}$.
     - Bullish CHOCH close requires: $\text{close}[k] > \text{last\_resistance.price}$.
   - Since $\text{tentative\_low.price} \le \text{last\_resistance.price}$, no single scalar close can satisfy $\text{close}[k] < \text{tentative\_low} \le \text{last\_resistance} < \text{close}[k]$.

3. **Intra-Bar Wicks vs. Close-Only Qualification**:
   - A wide candle whose wicks span across both structural levels (e.g. `high > tentative_high` and `low < last_support`) does not create an event ordering conflict. CHOCH and MSM continuation are **closing-price only** events; intra-bar wick touches do not constitute breaks.
   - This mathematical non-overlap applies strictly to whether a single close can satisfy both opposite break conditions. It does **not** settle the separate question of whether $p_2$'s close can simultaneously establish Point 3 and count as the first CHOCH close $c_1$ (which remains isolated under Section 4.1).

---

## 9. Verifiable Acceptance Criteria

| ID | Category | Requirement | Verifiable Criterion |
|:---|:---|:---|:---|
| **AC-CHOCH-01** | Bearish Confirmation | 2 consecutive closes strictly below last support | Both `c1.close < support` and `c2.close < support`; confirms at `c2.close_time`. |
| **AC-CHOCH-02** | Bullish Confirmation | 2 consecutive closes strictly above last resistance | Both `c1.close > resistance` and `c2.close > resistance`; confirms at `c2.close_time`. |
| **AC-CHOCH-03** | Single Close Rejection | Only 1 candle closes beyond level | CHOCH is NOT confirmed; state remains pending. |
| **AC-CHOCH-04** | Equality Rejection | Close exactly equal to support/resistance | `close == level` fails; pair does NOT confirm CHOCH. |
| **AC-CHOCH-05** | Non-Consecutive Closes | Qualifying closes separated by non-qualifying candle | Pair fails; cannot combine non-consecutive closes. |
| **AC-CHOCH-06** | Wick-Only Crossing | Wick breaches level but close does not | `low < support` but `close >= support` fails. |
| **AC-CHOCH-07** | Color Independence | Mixed green/red/flat qualifying candles | CHOCH confirms if closing price condition is met. |
| **AC-CHOCH-08** | Point 3 Prerequisite | No active tentative Point 3 identified | Closes below support do NOT confirm CHOCH without Point 3. |
| **AC-CHOCH-09** | Timing Eligibility | Close occurs strictly before Point 3 identified | Candle completing strictly before `p2.close_time` does NOT count toward CHOCH. Same-close case (`c1 == p2`) is explicitly isolated as UNRESOLVED. |
| **AC-CHOCH-10** | Cycle Completion Reset | Continuation break before CHOCH confirms | Point 3 becomes confirmed; tentative status lost; in-progress close count resets. |
| **AC-CHOCH-11** | High-Side Zone Geometry | Confirmed High, RBS, QML, Double Top | `[UB, High]` with body edge to wick tip. |
| **AC-CHOCH-12** | Low-Side Zone Geometry | Confirmed Low, SBR, QML, Double Bottom | `[Low, LB]` with wick tip to lower body edge. |
| **AC-CHOCH-13** | Zero-Wick Line Preservation | Original candle has zero relevant wick | Zone thickness is exactly 0 (`[price, price]`); no artificial widening. |
| **AC-CHOCH-14** | Cycle Termination & Restart | CHOCH confirmed | Old cycle terminates; direction reverses; restart reference is Point 3 candle. |
| **AC-CHOCH-15** | Post-Confirmation Pullback | First pullback in new direction | Both pullback candles must be strictly after `c2`. |

---

## 10. Checkpoint & Milestone Status: Bounded Dashboard Acceptance (HANDOFF-024)

- **Milestone Status**: Formally Accepted by Perplexity review for the bounded source-settled MSM+CHOCH dashboard scope at commit `9e4a33b672b1e82e36ea042ac84868a2fa10201a`.
- **Preserved Limitations & Boundary Qualifications**:
  1. **Isolated CHOCH Identification-Close Interpretation**: The unresolved question of whether candle $p_2$'s close can simultaneously establish Point 3 and count as the first CHOCH candidate close $c_1$ remains isolated as `INTEGRATED_STRUCTURE_UNRESOLVED`. Bounded milestone acceptance does not resolve it or establish complete integrated strategy coverage.
  2. **Browser Verification Evidence Characterization**: The deterministic browser verification (`tests/test_choch_browser_verification.py`) routes deterministic fixture datasets through H1 and D1 dropdown selector values. This confirms Dash/Plotly UI rendering, component lifecycle, coordinate calculation, and context switching; it does **not** validate genuine native broker H1/D1 candle boundaries. These results are recorded strictly as **fixture-backed rendering scenarios**, not timeframe-boundary verification.
- **Successor Scope**: Transition to source-backed Internal Structure Shift (ISS) requirements and acceptance fixtures under branch `requirements/iss-acceptance`.

