"""Market Structure Marking (MSM) strategy module for Aladeen / TopG.

Scope Boundary:
---------------
Read-only deterministic market structure calculation engine and application service.
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
    SUPPORTED_RULE_VERSIONS,
    adapt_chart_dataframe,
    calculate_msm,
    is_candle_completed,
    is_context_compatible,
    validate_candle_completion,
)

from .choch_types import (
    ChochCandidate,
    ChochDiagnostic,
    ChochDiagnosticType,
    ChochSnapshot,
    ChochType,
    ChochZone,
    ChochZoneType,
    ConfirmedChoch,
)
from .choch_detector import ChochDetector
from .coordinator import CoordinatorSnapshot, MSMChochCoordinator
from .iss_types import (
    CandidateIdentity,
    ConfirmedISSEvent,
    FrozenBoundary,
    ISSConfig,
    ISSDiagnosticType,
    ISSLifecycleStatus,
    ISSSnapshot,
    ISSZone,
    ISSZoneType,
    InternalFivePointStructure,
    InternalPoint,
)
from .iss_engine import ISSEngine

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
    "SUPPORTED_RULE_VERSIONS",
    "adapt_chart_dataframe",
    "calculate_msm",
    "is_candle_completed",
    "is_context_compatible",
    "validate_candle_completion",
    "ChochCandidate",
    "ChochDiagnostic",
    "ChochDiagnosticType",
    "ChochSnapshot",
    "ChochType",
    "ChochZone",
    "ChochZoneType",
    "ConfirmedChoch",
    "ChochDetector",
    "CoordinatorSnapshot",
    "MSMChochCoordinator",
    "CandidateIdentity",
    "ConfirmedISSEvent",
    "FrozenBoundary",
    "ISSConfig",
    "ISSDiagnosticType",
    "ISSLifecycleStatus",
    "ISSSnapshot",
    "ISSZone",
    "ISSZoneType",
    "InternalFivePointStructure",
    "InternalPoint",
    "ISSEngine",
]
