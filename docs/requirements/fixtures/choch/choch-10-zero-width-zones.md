# Fixture CHOCH-10: Zero-Width Zones Preserved as Price Lines

- **Source Section**: `Choch.pdf` / `docs/strategy/extracted/choch.md` Section 3.2 & `docs/requirements/approved-clarifications.md` (OPEN-10)
- **Machine-Readable Target**: `tests/fixtures/choch_acceptance.json` (`choch_zero_width_zones_preserved_as_price_lines`)

## Description
When the original swing candle of a zone has no wick on the qualifying boundary side:
- High-side zones (QML/A+ in upward structure, Double Top): upper boundary is `high`, lower boundary is `UB`. If `high == UB` (zero top wick), upper boundary equals lower boundary.
- Low-side zones (SBR in upward structure, QML/A+ in downward structure, Double Bottom): lower boundary is `low`, upper boundary is `LB`. If `low == LB` (zero bottom wick), lower boundary equals upper boundary.

The zone must be preserved as a single horizontal price line (`[price, price]`) with `is_line = true`. It is strictly prohibited to invent an artificial thickness, substitute neighboring wicks, or expand into neighboring bars.

## Original Candles

| Point Type | Open | Close | High | Low | Body Boundary | Wick Boundary | Zone Type | Resulting Geometry |
|---|---|---|---|---|---|---|---|---|
| Confirmed High | 1.120 | 1.135 | 1.135 | 1.115 | `UB = 1.135` | `High = 1.135` | QML / A+ | `[1.135, 1.135]`, `is_line = true` |
| Confirmed Low | 1.110 | 1.105 | 1.118 | 1.105 | `LB = 1.105` | `Low = 1.105` | SBR | `[1.105, 1.105]`, `is_line = true` |
| Point 3 | 1.150 | 1.155 | 1.160 | 1.145 | `UB = 1.155` | `High = 1.160` | Double Top | `[1.155, 1.160]`, `is_line = false` |

## Expected Behavior
- QML / A+ zone: `lower_price = 1.135`, `upper_price = 1.135`, `is_line = true`.
- SBR zone: `lower_price = 1.105`, `upper_price = 1.105`, `is_line = true`.
- Double Top zone: `lower_price = 1.155`, `upper_price = 1.160`, `is_line = false`.
