# Fixture CHOCH-14: Equal-Level Search Geometry Boundary

- **Source Authority**: `Market Structure Marking.docx` Section 3 (Upward Algorithm search window geometry) & `docs/strategy/Choch.pdf` Section 3.1; approved clarifications [`docs/requirements/approved-clarifications.md`](../../approved-clarifications.md) (OPEN-01, OPEN-03).
- **Fixture Category**: `synthetic_prerequisite_unit`, `source_settled`
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_equal_level_search_geometry_boundary`)

## Description
This fixture mathematically verifies the non-overlap of MSM continuation breaks and CHOCH breaks under the extreme boundary condition where `tentative_high.price == last_support.price`.

### Search Window Geometry
- In `Market Structure Marking.docx` Section 3, the tentative-high search window begins at `search_start`, which is the confirmed-low reference candle (`last_support`).
- Because any candle has $\text{UB} \ge \text{LB}$, evaluating upper body edges $\text{UB}$ across a window that contains `last_support` guarantees:
  $$\text{tentative\_high.price} \ge \text{last\_support.price}$$
- In the boundary case where `search_start` is a flat candle with zero body height ($\text{open} == \text{close} \implies \text{UB} == \text{LB} = 1.100$), and no other candle in the window has a higher $\text{UB}$:
  $$\text{tentative\_high.price} = 1.100 = \text{last\_support.price}$$

### Non-Overlap Proof
- Upward Continuation Break requires: $\text{close} > 1.100$ (strict inequality).
- Bearish CHOCH close requires: $\text{close} < 1.100$ (strict inequality).
- Single candle close evaluations:
  1. $\text{close} = 1.105 > 1.100$: Continuation satisfied (True), CHOCH satisfied (False).
  2. $\text{close} = 1.095 < 1.100$: Continuation satisfied (False), CHOCH satisfied (True).
  3. $\text{close} = 1.100 == 1.100$: Continuation satisfied (False), CHOCH satisfied (False) — equality fails closed for both!
- Conclusion: A single candle close can never satisfy both opposite conditions simultaneously, even at the exact mathematical boundary where $\text{tentative\_high} == \text{last\_support}$.
