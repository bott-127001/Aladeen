# Fixture Specification: `tjl_03_original_candle_geometry_and_zero_width_lines`

**Category**: end_to_end_msm_derived, source_settled  
**Scope**: Zone Geometry & Zero-Width Lines  

## 1. Description & Strategy Context
Verifies physical body-to-wick zone geometry from original candles across all four configurations:
1. High-side zone with top wick: `[max(open, close), high]`
2. High-side zone with zero top wick (marubozu: `max(open, close) == high`): single price line `[high, high]`
3. Low-side zone with bottom wick: `[low, min(open, close)]`
4. Low-side zone with zero bottom wick (marubozu: `min(open, close) == low`): single price line `[low, low]`

## 2. Geometric Requirements
- Zero relevant wick produces a labeled single price line.
- The zone is **never artificially widened**, buffered, or substituted with an adjacent candle.
- Upper price equals lower price ($y_0 == y_1$) in calculations.
