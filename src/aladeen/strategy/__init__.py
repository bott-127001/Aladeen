"""Market Structure Marking (MSM) strategy module for Aladeen / TopG.

Scope Boundary:
---------------
Read-only deterministic market structure calculation engine.
No MT5 connectivity, no Plotly/Dash UI, no CHOCH, no signals, no order execution.
"""

from .types import (
    CandleColor,
    ConfirmedPair,
    Direction,
    EngineState,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
    SwingPoint,
    TrendStatus,
)
from .validator import adapt_candles, validate_start_candle
from .engine import MSMEngine
from .service import (
    MSMContext,
    MSMServiceResult,
    adapt_chart_dataframe,
    calculate_msm,
    is_context_compatible,
)

__all__ = [
    "CandleColor",
    "ConfirmedPair",
    "Direction",
    "EngineState",
    "MSMConfig",
    "MSMSnapshot",
    "StrategyCandle",
    "SwingPoint",
    "TrendStatus",
    "adapt_candles",
    "validate_start_candle",
    "MSMEngine",
    "MSMContext",
    "MSMServiceResult",
    "adapt_chart_dataframe",
    "calculate_msm",
    "is_context_compatible",
]
