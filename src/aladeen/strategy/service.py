"""Application service layer for Market Structure Marking (MSM).

Bridges UI / data adapters and pure domain logic:
- Adapts chart DataFrames (Demo / MT5) to validated immutable StrategyCandles.
- Validates context compatibility across symbol / timeframe / data source changes.
- Derives stable integer IDs from UTC timestamps when explicit integer index is absent.
- Enforces strict explicit completion evidence (no silent defaulting).
- Executes fresh batch MSM runs via MSMEngine.
- Returns immutable MSMServiceResult structures containing snapshot and diagnostic provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import threading
import numpy as np
import pandas as pd

from .activation_engine import ActivationEngine, ActivationEngineConfig
from .activation_adapter import TJLSynchronizer
from .activation_types import (
    ActivationSnapshot,
    ExactPricePrint,
    PriceBasis,
    SequenceDomain,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
)
from .coordinator import CoordinatorSnapshot, MSMChochCoordinator
from .choch_types import ChochDiagnostic, ConfirmedChoch
from .engine import MSMEngine
from .iss_engine import ISSEngine
from .iss_types import (
    ConfirmedISSEvent,
    ISSConfig,
    ISSLifecycleStatus,
    ISSSnapshot,
    ISSZone,
)
from .tjl_coordinator import TJLCoordinator
from .tjl_types import StableLevelId, TJLSnapshot
from .types import (
    Direction,
    EngineState,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
    SwingPoint,
    ConfirmedPair,
    TrendStatus,
    VALID_BAR_STATUSES,
    validate_and_normalize_timestamp,
)
from .validator import adapt_candles, validate_start_candle

SUPPORTED_RULE_VERSIONS: Set[str] = {"1.0"}


class CalculationMode(str, Enum):
    """Strategy calculation mode."""
    STANDALONE_MSM = "STANDALONE_MSM"
    INTEGRATED_MSM_CHOCH = "INTEGRATED_MSM_CHOCH"
    INTEGRATED_MSM_CHOCH_ISS = "INTEGRATED_MSM_CHOCH_ISS"
    INTEGRATED_MSM_CHOCH_TJL = "INTEGRATED_MSM_CHOCH_TJL"


def validate_candle_completion(row_pos: int, row: Any) -> Tuple[bool, str]:
    """Strictly validates candle completion evidence fields.

    Rules & Invariants (R10.1):
    ---------------------------
    - Requires explicit 'is_forming' and 'bar_status' fields.
    - Rejects missing, null, or NaN completion fields with ValueError.
    - Accepts legitimate bool or np.bool_ for is_forming; rejects strings, numbers, etc. with TypeError.
    - Validates bar_status is an exact string belonging to VALID_BAR_STATUSES without loose coercions.
    - Rejects contradictory completion evidence:
      - is_forming=True with bar_status='CONFIRMED_COMPLETED' (ValueError)
      - is_forming=False with bar_status in {'UNCONFIRMED_LATEST', 'FORMING'} (ValueError)
    """
    if "is_forming" not in row:
        raise ValueError(f"Row {row_pos} missing required completion field 'is_forming'.")

    raw_forming = row["is_forming"]
    if pd.isna(raw_forming) if hasattr(pd, "isna") else raw_forming is None:
        raise ValueError(f"Row {row_pos} 'is_forming' cannot be null/NaN.")

    if isinstance(raw_forming, (bool, np.bool_)):
        is_forming = bool(raw_forming)
    else:
        raise TypeError(
            f"Row {row_pos} 'is_forming' must be bool, got {type(raw_forming).__name__} ({raw_forming})"
        )

    if "bar_status" not in row:
        raise ValueError(f"Row {row_pos} missing required completion field 'bar_status'.")

    raw_status = row["bar_status"]
    if pd.isna(raw_status) if hasattr(pd, "isna") else raw_status is None:
        raise ValueError(f"Row {row_pos} 'bar_status' cannot be null/NaN.")

    if not isinstance(raw_status, str):
        raise TypeError(
            f"Row {row_pos} 'bar_status' must be str, got {type(raw_status).__name__} ({raw_status})"
        )

    if raw_status not in VALID_BAR_STATUSES:
        raise ValueError(
            f"Row {row_pos} unknown bar_status '{raw_status}'. Must be one of {sorted(VALID_BAR_STATUSES)}"
        )

    if is_forming and raw_status == "CONFIRMED_COMPLETED":
        raise ValueError(
            f"Row {row_pos} contradictory completion evidence: is_forming=True cannot have bar_status='CONFIRMED_COMPLETED'"
        )

    if not is_forming and raw_status in {"UNCONFIRMED_LATEST", "FORMING"}:
        raise ValueError(
            f"Row {row_pos} contradictory completion evidence: is_forming=False cannot have bar_status='{raw_status}'"
        )

    return is_forming, raw_status


def is_candle_completed(row_pos: int, row: Any) -> bool:
    """Predicate evaluating whether a candle row is verified completed.

    Fails closed with errors if completion evidence is malformed or contradictory.
    """
    is_forming, bar_status = validate_candle_completion(row_pos, row)
    return (not is_forming) and (bar_status == "CONFIRMED_COMPLETED")


@dataclass(frozen=True)
class MSMContext:
    """Configuration context for an applied MSM / Strategy calculation."""
    data_source: str
    symbol: str
    timeframe: str
    start_candle_time: datetime
    direction: Direction
    rule_version: str = "1.0"
    enabled: bool = True
    calculation_mode: str = CalculationMode.STANDALONE_MSM.value
    show_choch_zones: bool = True
    show_choch_markers: bool = True
    show_iss_markers: bool = True
    show_iss_zones: bool = True
    show_iss_points: bool = True
    show_tjl_zones: bool = True
    show_tjl_labels: bool = True
    show_tjl_current_set: bool = True
    show_tjl_historical_sets: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.data_source, str) or not self.data_source.strip():
            raise TypeError(f"data_source must be a non-empty string, got {type(self.data_source).__name__}")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise TypeError(f"symbol must be a non-empty string, got {type(self.symbol).__name__}")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise TypeError(f"timeframe must be a non-empty string, got {type(self.timeframe).__name__}")

        norm_start = validate_and_normalize_timestamp(self.start_candle_time, "start_candle_time")
        object.__setattr__(self, "start_candle_time", norm_start)

        if isinstance(self.direction, str):
            try:
                object.__setattr__(self, "direction", Direction(self.direction))
            except ValueError:
                raise ValueError(
                    f"Invalid direction '{self.direction}': must be Direction.UPWARD or Direction.DOWNWARD"
                )
        elif not isinstance(self.direction, Direction):
            raise TypeError(f"direction must be Direction enum, got {type(self.direction).__name__}")

        if not isinstance(self.rule_version, str) or self.rule_version not in SUPPORTED_RULE_VERSIONS:
            raise ValueError(
                f"Unsupported rule_version '{self.rule_version}'. Supported: {sorted(SUPPORTED_RULE_VERSIONS)}"
            )

        if isinstance(self.enabled, (bool, np.bool_)):
            object.__setattr__(self, "enabled", bool(self.enabled))
        else:
            raise TypeError(f"enabled must be bool, got {type(self.enabled).__name__} ({self.enabled})")

        valid_modes = {
            CalculationMode.STANDALONE_MSM.value,
            CalculationMode.INTEGRATED_MSM_CHOCH.value,
            CalculationMode.INTEGRATED_MSM_CHOCH_ISS.value,
            CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value,
        }
        if self.calculation_mode not in valid_modes:
            raise ValueError(f"Unknown calculation_mode '{self.calculation_mode}'. Must be one of {valid_modes}")

        object.__setattr__(self, "show_choch_zones", bool(self.show_choch_zones))
        object.__setattr__(self, "show_choch_markers", bool(self.show_choch_markers))
        object.__setattr__(self, "show_iss_markers", bool(self.show_iss_markers))
        object.__setattr__(self, "show_iss_zones", bool(self.show_iss_zones))
        object.__setattr__(self, "show_iss_points", bool(self.show_iss_points))
        object.__setattr__(self, "show_tjl_zones", bool(self.show_tjl_zones))
        object.__setattr__(self, "show_tjl_labels", bool(self.show_tjl_labels))
        object.__setattr__(self, "show_tjl_current_set", bool(self.show_tjl_current_set))
        object.__setattr__(self, "show_tjl_historical_sets", bool(self.show_tjl_historical_sets))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize context to a JSON-compatible dictionary."""
        return {
            "data_source": self.data_source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_candle_time": self.start_candle_time.isoformat(),
            "direction": self.direction.value,
            "rule_version": self.rule_version,
            "enabled": self.enabled,
            "calculation_mode": self.calculation_mode,
            "show_choch_zones": self.show_choch_zones,
            "show_choch_markers": self.show_choch_markers,
            "show_iss_markers": self.show_iss_markers,
            "show_iss_zones": self.show_iss_zones,
            "show_iss_points": self.show_iss_points,
            "show_tjl_zones": self.show_tjl_zones,
            "show_tjl_labels": self.show_tjl_labels,
            "show_tjl_current_set": self.show_tjl_current_set,
            "show_tjl_historical_sets": self.show_tjl_historical_sets,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MSMContext:
        """Construct MSMContext from a dictionary with strict type validation (R10.5)."""
        if not isinstance(data, dict):
            raise TypeError(f"data must be dict, got {type(data).__name__}")

        for field_name in ["data_source", "symbol", "timeframe", "start_candle_time", "direction"]:
            if field_name not in data or data[field_name] is None:
                raise ValueError(f"Missing required context field: '{field_name}'")

        if not isinstance(data["data_source"], str):
            raise TypeError(f"data_source must be str, got {type(data['data_source']).__name__}")
        if not isinstance(data["symbol"], str):
            raise TypeError(f"symbol must be str, got {type(data['symbol']).__name__}")
        if not isinstance(data["timeframe"], str):
            raise TypeError(f"timeframe must be str, got {type(data['timeframe']).__name__}")

        raw_enabled = data.get("enabled", True)
        if not isinstance(raw_enabled, (bool, np.bool_)):
            raise TypeError(f"enabled must be bool, got {type(raw_enabled).__name__} ({raw_enabled})")

        rule_ver = data.get("rule_version", "1.0")
        if not isinstance(rule_ver, str) or rule_ver not in SUPPORTED_RULE_VERSIONS:
            raise ValueError(f"Unsupported rule_version '{rule_ver}'. Supported: {sorted(SUPPORTED_RULE_VERSIONS)}")

        raw_dir = data["direction"]
        if not isinstance(raw_dir, (str, Direction)):
            raise TypeError(f"direction must be str or Direction, got {type(raw_dir).__name__}")

        start_time = validate_and_normalize_timestamp(data["start_candle_time"], "start_candle_time")
        calc_mode = data.get("calculation_mode", CalculationMode.STANDALONE_MSM.value)
        show_zones = bool(data.get("show_choch_zones", True))
        show_markers = bool(data.get("show_choch_markers", True))
        show_iss_markers = bool(data.get("show_iss_markers", True))
        show_iss_zones = bool(data.get("show_iss_zones", True))
        show_iss_points = bool(data.get("show_iss_points", True))
        show_tjl_zones = bool(data.get("show_tjl_zones", True))
        show_tjl_labels = bool(data.get("show_tjl_labels", True))
        show_tjl_current_set = bool(data.get("show_tjl_current_set", True))
        show_tjl_historical_sets = bool(data.get("show_tjl_historical_sets", True))

        return cls(
            data_source=data["data_source"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            start_candle_time=start_time,
            direction=Direction(raw_dir) if isinstance(raw_dir, str) else raw_dir,
            rule_version=rule_ver,
            enabled=bool(raw_enabled),
            calculation_mode=calc_mode,
            show_choch_zones=show_zones,
            show_choch_markers=show_markers,
            show_iss_markers=show_iss_markers,
            show_iss_zones=show_iss_zones,
            show_iss_points=show_iss_points,
            show_tjl_zones=show_tjl_zones,
            show_tjl_labels=show_tjl_labels,
            show_tjl_current_set=show_tjl_current_set,
            show_tjl_historical_sets=show_tjl_historical_sets,
        )


@dataclass(frozen=True)
class MSMServiceResult:
    """Immutable result structure of an MSM / CHOCH / ISS / TJL service calculation."""
    context: MSMContext
    snapshot: Optional[MSMSnapshot]
    candles: Tuple[StrategyCandle, ...]
    status_message: str
    candle_count: int
    start_candle_found: bool
    coordinator_snapshot: Optional[CoordinatorSnapshot] = None
    confirmed_choch_events: Tuple[ConfirmedChoch, ...] = ()
    iss_snapshot: Optional[ISSSnapshot] = None
    confirmed_iss_events: Tuple[ConfirmedISSEvent, ...] = ()
    tjl_snapshot: Optional[TJLSnapshot] = None
    activation_snapshot: Optional[ActivationSnapshot] = None
    last_synced_transition_index: Optional[int] = None
    exact_observation_count: Optional[int] = None
    activation_error: Optional[str] = None
    is_unresolved: bool = False
    unresolved_diagnostic: Optional[ChochDiagnostic] = None
    unresolved_candle_index: Optional[int] = None
    last_processed_index: int = -1
    last_received_index: int = -1
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """True if calculation completed successfully and produced a valid snapshot."""
        return self.snapshot is not None and self.error is None


class ActivationSessionCoordinator:
    """Session coordinator owning the activation engine and TJL-to-activation synchronizer.

    Responsibilities:
    -----------------
    - Retains single active ActivationEngine and TJLSynchronizer across sequential service calculations.
    - Synchronizes authoritative TJLSnapshot outputs produced during integrated calculations.
    - Enforces context boundaries: resets engine and synchronizer state when data_source, engine_id,
      symbol, timeframe, start candle, or explicit run_id changes.
    - Distinguishes incremental synchronization within the same run from explicit recalculation.
    - Maintains strictly monotonic sequence allocation across successive sync calls within a run.
    - Preserves engine state on sync failures and emits descriptive error diagnostics.
    - Strictly non-inventing: never synthesizes price prints or overrides fail-closed UNKNOWN usage status in candle-only runs.
    """

    def __init__(self, sequence_domain_run_id: str = "OFFLINE_SERVICE_RUN") -> None:
        self._initial_run_id = sequence_domain_run_id
        self._current_run_id = sequence_domain_run_id
        self._run_counter: int = 1
        self._engine: Optional[ActivationEngine] = None
        self._synchronizer: Optional[TJLSynchronizer] = None
        self._bound_context_key: Optional[Tuple[str, str, str, str, datetime, str]] = None
        self._last_synced_transition_index: Optional[int] = None
        self._next_sequence_ref: int = 0
        self._last_sync_error: Optional[str] = None

    @property
    def engine(self) -> Optional[ActivationEngine]:
        return self._engine

    @property
    def synchronizer(self) -> Optional[TJLSynchronizer]:
        return self._synchronizer

    @property
    def current_run_id(self) -> str:
        return self._current_run_id

    @property
    def last_synced_transition_index(self) -> Optional[int]:
        return self._last_synced_transition_index

    @property
    def last_sync_error(self) -> Optional[str]:
        return self._last_sync_error

    @property
    def next_sequence_ref(self) -> int:
        return self._next_sequence_ref

    @property
    def exact_observation_count(self) -> Optional[int]:
        """Diagnostic count of exact observation events processed by the engine.

        Returns count of successfully accepted distinct ExactPricePrint observations,
        or None if no tick evidence boundary is present.
        """
        if self._engine is not None and self._engine._processed_events:
            exact_count = sum(
                1 for ev in self._engine._processed_events.values()
                if isinstance(ev, ExactPricePrint)
            )
            return exact_count if exact_count > 0 else None
        return None

    def reset(self, new_run_id: Optional[str] = None) -> None:
        """Resets engine, synchronizer, sequence counter, and context binding to clean initial baseline."""
        if self._engine is not None:
            self._engine.reset()
        self._engine = None
        self._synchronizer = None
        self._bound_context_key = None
        self._last_synced_transition_index = None
        self._next_sequence_ref = 0
        self._last_sync_error = None
        if new_run_id is not None:
            self._current_run_id = new_run_id

    def start_new_run(self) -> str:
        """Advances to a fresh run ID, triggering a clean recalculation cycle on next sync."""
        self._run_counter += 1
        self._current_run_id = f"{self._initial_run_id}_{self._run_counter}"
        self.reset(self._current_run_id)
        return self._current_run_id

    def process_exact_price_print(self, print_event: ExactPricePrint) -> ActivationSnapshot:
        """Dispatches an authoritative ExactPricePrint through the coordinator boundary.

        Reconciles sequence high-water marks before and after event processing.
        """
        if self._engine is None:
            raise RuntimeError("Cannot process price print: activation engine not initialized.")
        if not isinstance(print_event, ExactPricePrint):
            raise TypeError(f"Expected ExactPricePrint, got {type(print_event).__name__}")

        # High-water mark check before event processing
        if self._engine._last_processed_sequence is not None:
            self._next_sequence_ref = max(self._next_sequence_ref, self._engine._last_processed_sequence + 1)

        snap = self._engine.process_event(print_event)

        # Update high-water mark after event processing
        if self._engine._last_processed_sequence is not None:
            self._next_sequence_ref = max(self._next_sequence_ref, self._engine._last_processed_sequence + 1)

        return snap

    def sync_tjl_snapshot(
        self,
        tjl_snapshot: TJLSnapshot,
        context: MSMContext,
        *,
        usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
        force_recalculation: bool = False,
        run_id: Optional[str] = None,
    ) -> Optional[ActivationSnapshot]:
        """Synchronizes an authoritative TJLSnapshot into the session ActivationEngine.

        Enforces context boundaries across data_source, engine_id, symbol, timeframe,
        start_candle_time, and run_id.
        """
        if not isinstance(tjl_snapshot, TJLSnapshot):
            raise TypeError(f"Expected TJLSnapshot, got {type(tjl_snapshot).__name__}")

        if force_recalculation:
            active_run_id = self.start_new_run()
        elif run_id is not None:
            active_run_id = run_id
            self._current_run_id = run_id
        else:
            active_run_id = self._current_run_id

        data_source = context.data_source
        engine_id = tjl_snapshot.source_engine_id
        symbol = tjl_snapshot.symbol_feed_id
        tf = tjl_snapshot.source_timeframe
        start_time = context.start_candle_time

        context_key = (data_source, engine_id, symbol, tf, start_time, active_run_id)

        # Detect context switch or recalculation
        if force_recalculation or self._bound_context_key != context_key:
            self.reset(active_run_id)
            self._bound_context_key = context_key

            # Only initialize if source timeframe is in confirmation map
            if tf not in TIMEFRAME_CONFIRMATION_MAP:
                return None

            seq_domain = SequenceDomain(
                feed_id=f"FEED_{symbol}_{tf}",
                run_id=active_run_id,
            )
            config = ActivationEngineConfig(
                engine_id=engine_id,
                symbol=symbol,
                source_timeframe=tf,
                sequence_domain=seq_domain,
                price_basis=PriceBasis.BID,
            )
            self._engine = ActivationEngine(config)
            self._synchronizer = TJLSynchronizer(engine=self._engine)

        if self._synchronizer is None or self._engine is None:
            return None

        # Reconcile sequence high-water mark before synchronization
        if self._engine._last_processed_sequence is not None:
            self._next_sequence_ref = max(self._next_sequence_ref, self._engine._last_processed_sequence + 1)

        # Synchronize using strictly monotonic sequence counter
        try:
            act_snap = self._synchronizer.sync(
                snapshot=tjl_snapshot,
                sequence_ref_start=self._next_sequence_ref,
                usage_evidence=usage_evidence,
            )
            self._last_synced_transition_index = self._synchronizer.last_synced_transition_index
            self._last_sync_error = None

            # Monotonically update next sequence ref
            if self._engine._last_processed_sequence is not None:
                self._next_sequence_ref = max(self._next_sequence_ref, self._engine._last_processed_sequence + 1)

            return act_snap
        except Exception as e:
            # Preserve prior valid state on failure; record error diagnostic
            self._last_sync_error = str(e)
            raise



class ActivationSessionRegistry:
    """Thread-safe, bounded session registry managing ActivationSessionCoordinator instances.

    Responsibilities:
    -----------------
    - Provides isolated ActivationSessionCoordinator instances per session_id.
    - Prevents cross-session interference (two sessions with same or different contexts never share state).
    - Enforces bounded capacity with LRU eviction to prevent unbounded memory growth in long-running processes.
    - Supports explicit eviction, inspection, and clearing.
    """

    def __init__(self, max_sessions: int = 100) -> None:
        self._max_sessions = max_sessions
        self._sessions: Dict[str, ActivationSessionCoordinator] = {}
        self._access_order: List[str] = []
        self._lock = threading.Lock()

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    @property
    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def get_or_create(self, session_id: str, run_id_prefix: Optional[str] = None) -> ActivationSessionCoordinator:
        """Returns the isolated ActivationSessionCoordinator for session_id, creating one if absent."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError(f"session_id must be a non-empty string, got {session_id!r}")

        with self._lock:
            if session_id in self._sessions:
                # Move to end of LRU access order
                if session_id in self._access_order:
                    self._access_order.remove(session_id)
                self._access_order.append(session_id)
                return self._sessions[session_id]

            # Bounded LRU eviction
            while len(self._sessions) >= self._max_sessions and self._access_order:
                lru_id = self._access_order.pop(0)
                evicted = self._sessions.pop(lru_id, None)
                if evicted is not None:
                    evicted.reset()

            prefix = run_id_prefix or f"SESSION_{session_id}"
            coord = ActivationSessionCoordinator(sequence_domain_run_id=prefix)
            self._sessions[session_id] = coord
            self._access_order.append(session_id)
            return coord

    def remove_session(self, session_id: str) -> None:
        """Explicitly evicts and resets a session."""
        with self._lock:
            coord = self._sessions.pop(session_id, None)
            if coord is not None:
                coord.reset()
            if session_id in self._access_order:
                self._access_order.remove(session_id)

    def clear(self) -> None:
        """Clears and resets all managed sessions."""
        with self._lock:
            for coord in self._sessions.values():
                coord.reset()
            self._sessions.clear()
            self._access_order.clear()


_default_session_registry: Optional[ActivationSessionRegistry] = None


def get_activation_session_registry() -> ActivationSessionRegistry:
    """Returns the process-level ActivationSessionRegistry."""
    global _default_session_registry
    if _default_session_registry is None:
        _default_session_registry = ActivationSessionRegistry()
    return _default_session_registry


def reset_activation_session_registry() -> None:
    """Clears and resets the process-level ActivationSessionRegistry."""
    global _default_session_registry
    if _default_session_registry is not None:
        _default_session_registry.clear()

_default_session_coordinator: Optional[ActivationSessionCoordinator] = None


def get_default_activation_coordinator() -> ActivationSessionCoordinator:
    """Returns the process-level default ActivationSessionCoordinator."""
    global _default_session_coordinator
    if _default_session_coordinator is None:
        _default_session_coordinator = ActivationSessionCoordinator()
    return _default_session_coordinator


def reset_activation_coordinator() -> None:
    """Resets the process-level default ActivationSessionCoordinator."""
    global _default_session_coordinator
    if _default_session_coordinator is not None:
        _default_session_coordinator.reset()



def adapt_chart_dataframe(df: pd.DataFrame) -> List[StrategyCandle]:
    """Adapts a chart OHLC DataFrame into a sequence of validated StrategyCandle objects.

    Rules & Invariants (R10.1):
    ---------------------------
    1. df must have a UTC-aware DatetimeIndex without nulls / NaT.
    2. Required columns: open, high, low, close, is_forming, bar_status.
    3. Scalar handling: Supports int, float, np.integer, np.floating.
       Strictly rejects bool, np.bool_, strings, NaN, +/-inf.
    4. Stable Identity: If df contains an integer 'index' column, it is used.
       If absent, derives a stable integer ID from the UTC open timestamp
       (int(open_time.timestamp())), preserving identity across window shifts.
    5. Explicit Completion: Strictly validates completion fields via
       `validate_candle_completion`. Reject missing or null completion evidence.
    """
    if df is None:
        raise ValueError("DataFrame cannot be None.")
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected pandas DataFrame, got {type(df).__name__}")
    if df.empty:
        raise ValueError("DataFrame is empty.")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame must have a DatetimeIndex.")
    if df.index.tz is None:
        raise ValueError("DataFrame index must be timezone-aware (UTC).")
    if df.index.hasnans:
        raise ValueError("DataFrame index contains NaT.")

    required_cols = {"open", "high", "low", "close", "is_forming", "bar_status"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required candle columns: {sorted(missing)}")

    candles: List[StrategyCandle] = []

    for row_pos, (ts, row) in enumerate(df.iterrows()):
        open_time = validate_and_normalize_timestamp(ts, f"Row {row_pos} open timestamp")

        # Validate numeric prices strictly
        for col in ["open", "high", "low", "close"]:
            val = row[col]
            if isinstance(val, (bool, np.bool_)):
                raise TypeError(f"Row {row_pos} '{col}' cannot be boolean ({val}).")
            if not isinstance(val, (int, float, np.integer, np.floating)):
                raise TypeError(f"Row {row_pos} '{col}' must be numeric, got {type(val).__name__} ({val}).")
            f_val = float(val)
            if not math.isfinite(f_val):
                raise ValueError(f"Row {row_pos} '{col}' must be finite, got {f_val}.")
            if f_val <= 0:
                raise ValueError(f"Row {row_pos} '{col}' must be positive, got {f_val}.")

        # Explicit completion validation (R10.1)
        is_forming, bar_status = validate_candle_completion(row_pos, row)

        close_time: Optional[datetime] = None
        if "close_time" in row and pd.notna(row["close_time"]):
            close_time = validate_and_normalize_timestamp(row["close_time"], f"Row {row_pos} close timestamp")

        # Stable integer index derivation
        if "index" in row and pd.notna(row["index"]):
            raw_idx = row["index"]
            if isinstance(raw_idx, (bool, np.bool_)) or not isinstance(raw_idx, (int, np.integer)):
                raise TypeError(f"Row {row_pos} 'index' must be int, got {type(raw_idx).__name__} ({raw_idx})")
            candle_index = int(raw_idx)
        else:
            # Stable integer ID derived from UTC epoch seconds
            candle_index = int(open_time.timestamp())

        candle = StrategyCandle(
            index=candle_index,
            open_time=open_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            is_forming=is_forming,
            bar_status=bar_status,
            close_time=close_time,
        )
        candles.append(candle)

    # Monotonic order check
    for i in range(1, len(candles)):
        if candles[i].open_time <= candles[i - 1].open_time:
            raise ValueError(
                f"Candle sequence not strictly monotonically increasing: "
                f"Candle {i} ({candles[i].open_time}) <= Candle {i-1} ({candles[i-1].open_time})"
            )

    return candles


def calculate_msm(
    df: pd.DataFrame,
    context: MSMContext,
    *,
    session_id: Optional[str] = None,
    activation_coordinator: Optional[ActivationSessionCoordinator] = None,
    usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
    force_recalculation: bool = False,
    run_id: Optional[str] = None,
) -> MSMServiceResult:
    """Performs a deterministic, fresh batch MSM calculation on *df* using *context*.

    Returns an MSMServiceResult. Fails closed with descriptive error messages
    if the starting candle is missing or forming.
    """
    try:
        candles = adapt_chart_dataframe(df)
    except Exception as e:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(),
            status_message=f"Failed to adapt candle data: {e}",
            candle_count=0,
            start_candle_found=False,
            error=str(e),
        )

    # Locate starting candle by open timestamp
    target_time = context.start_candle_time
    start_candle: Optional[StrategyCandle] = None
    for c in candles:
        if c.open_time == target_time:
            start_candle = c
            break

    if start_candle is None:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(candles),
            status_message=(
                f"Selected starting candle ({target_time.strftime('%Y-%m-%d %H:%M UTC')}) "
                f"not found in loaded chart data ({len(candles)} candles). "
                f"It may have fallen outside the history window."
            ),
            candle_count=len(candles),
            start_candle_found=False,
            error=(
                f"Starting candle {target_time.strftime('%Y-%m-%d %H:%M UTC')} "
                f"not found in loaded history window."
            ),
        )

    if start_candle.is_forming:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(candles),
            status_message="Selected starting candle is still forming / unconfirmed.",
            candle_count=len(candles),
            start_candle_found=True,
            error="Selected starting candle is still forming / unconfirmed and cannot be used as start candle.",
        )

    try:
        config = MSMConfig(
            start_candle_time=context.start_candle_time,
            direction=context.direction,
        )
        if context.calculation_mode == CalculationMode.INTEGRATED_MSM_CHOCH_TJL.value:
            tjl_coord = TJLCoordinator(
                config=config,
                symbol_feed_id=context.symbol,
                source_timeframe=context.timeframe,
                source_engine_id=f"ENGINE_{context.symbol}_{context.timeframe}",
            )
            tjl_snap = tjl_coord.process_candles(candles)
            coord_snap = tjl_coord.get_main_coordinator_snapshot()
            snapshot = coord_snap.msm_snapshot
            pair_count = len(snapshot.confirmed_pairs) if snapshot else 0
            choch_count = len(coord_snap.confirmed_choch_events)
            labeled_zone_count = len(tjl_snap.all_labeled_zones)
            curr_set_id = tjl_snap.current_eligible_set.set_id if tjl_snap.current_eligible_set else "None"

            if tjl_snap.is_unresolved or coord_snap.is_unresolved:
                unres_diag = tjl_snap.unresolved_diagnostic or (
                    coord_snap.unresolved_diagnostic.diagnostic_type.value
                    if coord_snap.unresolved_diagnostic else "Structure ambiguity"
                )
                status_msg = (
                    f"Integrated TJL unresolved: {unres_diag} | "
                    f"Last Authoritative State: {snapshot.trend_status if snapshot else 'None'} (Bar #{tjl_snap.last_processed_index}) | "
                    f"Received through Bar #{tjl_snap.last_received_index} | "
                    f"Pairs: {pair_count} | CHOCH: {choch_count} | Set: {curr_set_id}"
                )
            else:
                applied_dir_str = (
                    tjl_snap.direction.value
                    if tjl_snap.direction is not None
                    else context.direction.value
                )
                status_msg = (
                    f"MSM+CHOCH+TJL Applied: {applied_dir_str} (Epoch {tjl_snap.structural_epoch}) | "
                    f"Pairs: {pair_count} | CHOCH: {choch_count} | "
                    f"Eligible Set: {curr_set_id} | Labeled Zones: {labeled_zone_count}"
                )

            # Synchronize authoritative TJLSnapshot to session-managed ActivationEngine
            act_snap = None
            last_sync_idx = None
            exact_obs_count = None
            act_error = None
            if activation_coordinator is not None:
                act_coordinator = activation_coordinator
            elif session_id is not None:
                act_coordinator = get_activation_session_registry().get_or_create(session_id)
            else:
                act_coordinator = get_default_activation_coordinator()
            try:
                act_snap = act_coordinator.sync_tjl_snapshot(
                    tjl_snapshot=tjl_snap,
                    context=context,
                    usage_evidence=usage_evidence,
                    force_recalculation=force_recalculation,
                    run_id=run_id,
                )
                last_sync_idx = act_coordinator.last_synced_transition_index
                exact_obs_count = act_coordinator.exact_observation_count
                act_error = act_coordinator.last_sync_error
            except Exception as e:
                act_error = str(e)
                # Preserve prior valid snapshot if available
                act_snap = act_coordinator.engine.get_snapshot() if act_coordinator.engine else None
                last_sync_idx = act_coordinator.last_synced_transition_index
                exact_obs_count = act_coordinator.exact_observation_count

            return MSMServiceResult(
                context=context,
                snapshot=snapshot,
                candles=tuple(candles),
                status_message=status_msg,
                candle_count=len(candles),
                start_candle_found=True,
                coordinator_snapshot=coord_snap,
                confirmed_choch_events=coord_snap.confirmed_choch_events,
                tjl_snapshot=tjl_snap,
                activation_snapshot=act_snap,
                last_synced_transition_index=last_sync_idx,
                exact_observation_count=exact_obs_count,
                activation_error=act_error,
                is_unresolved=tjl_snap.is_unresolved or coord_snap.is_unresolved,
                unresolved_diagnostic=coord_snap.unresolved_diagnostic,
                unresolved_candle_index=coord_snap.unresolved_candle_index,
                last_processed_index=tjl_snap.last_processed_index,
                last_received_index=tjl_snap.last_received_index,
                error=None,
            )
        elif context.calculation_mode == CalculationMode.INTEGRATED_MSM_CHOCH_ISS.value:
            iss_config = ISSConfig(
                start_candle_time=context.start_candle_time,
                main_direction=context.direction,
            )
            iss_engine = ISSEngine(iss_config)
            iss_snap = iss_engine.process_candles(candles)

            # Public authoritative combined result from the ISS engine
            combined = iss_engine.get_combined_result()
            coord_snap = combined.main_coordinator_snapshot
            snapshot = coord_snap.msm_snapshot
            pair_count = len(snapshot.confirmed_pairs) if snapshot else 0
            choch_count = len(coord_snap.confirmed_choch_events)
            iss_event_count = len(combined.confirmed_iss_events)

            if iss_snap.is_unresolved or coord_snap.is_unresolved:
                unres_dep = iss_snap.unresolved_dependency or "Main CHOCH ambiguity"
                status_msg = (
                    f"Integrated ISS unresolved: {unres_dep} | "
                    f"Last Authoritative State: {snapshot.trend_status if snapshot else 'None'} (Bar #{iss_snap.last_processed_index}) | "
                    f"Received through Bar #{iss_snap.last_received_index} | "
                    f"Pairs: {pair_count} | CHOCH: {choch_count} | ISS: {iss_snap.lifecycle_status.value}"
                )
            else:
                applied_dir_str = iss_engine.direction.value
                status_msg = (
                    f"MSM+CHOCH+ISS Applied: {applied_dir_str} | "
                    f"Pairs: {pair_count} | CHOCH: {choch_count} | "
                    f"ISS: {iss_snap.lifecycle_status.value} ({iss_event_count} confirmed) | "
                    f"Trend: {snapshot.trend_status if snapshot else 'None'}"
                )

            return MSMServiceResult(
                context=context,
                snapshot=snapshot,
                candles=tuple(candles),
                status_message=status_msg,
                candle_count=len(candles),
                start_candle_found=True,
                coordinator_snapshot=coord_snap,
                confirmed_choch_events=coord_snap.confirmed_choch_events,
                iss_snapshot=iss_snap,
                confirmed_iss_events=iss_snap.confirmed_events,
                is_unresolved=iss_snap.is_unresolved or coord_snap.is_unresolved,
                unresolved_diagnostic=coord_snap.unresolved_diagnostic,
                unresolved_candle_index=coord_snap.unresolved_candle_index,
                last_processed_index=iss_snap.last_processed_index,
                last_received_index=iss_snap.last_received_index,
                error=None,
            )
        elif context.calculation_mode == CalculationMode.INTEGRATED_MSM_CHOCH.value:
            coordinator = MSMChochCoordinator(config)
            coord_snap = coordinator.process_candles(candles)
            snapshot = coord_snap.msm_snapshot
            pair_count = len(snapshot.confirmed_pairs) if snapshot else 0
            choch_count = len(coord_snap.confirmed_choch_events)

            if coord_snap.is_unresolved:
                status_msg = (
                    f"Integrated structure unresolved: ambiguous at candle {coord_snap.unresolved_candle_index} | "
                    f"Last Authoritative State: {snapshot.trend_status if snapshot else 'None'} (Bar #{coord_snap.last_processed_index}) | "
                    f"Received through Bar #{coord_snap.last_received_index} | "
                    f"Pairs: {pair_count} | CHOCH: {choch_count}"
                )
            else:
                applied_dir_str = (
                    coord_snap.active_direction.value
                    if coord_snap.active_direction is not None
                    else context.direction.value
                )
                status_msg = (
                    f"MSM+CHOCH Applied: {applied_dir_str} | "
                    f"Pairs: {pair_count} | CHOCH: {choch_count} | "
                    f"Trend: {snapshot.trend_status if snapshot else 'None'}"
                )
            return MSMServiceResult(
                context=context,
                snapshot=snapshot,
                candles=tuple(candles),
                status_message=status_msg,
                candle_count=len(candles),
                start_candle_found=True,
                coordinator_snapshot=coord_snap,
                confirmed_choch_events=coord_snap.confirmed_choch_events,
                is_unresolved=coord_snap.is_unresolved,
                unresolved_diagnostic=coord_snap.unresolved_diagnostic,
                unresolved_candle_index=coord_snap.unresolved_candle_index,
                last_processed_index=coord_snap.last_processed_index,
                last_received_index=coord_snap.last_received_index,
                error=None,
            )
        else:
            engine = MSMEngine(config)
            snapshot = engine.process_candles(candles)
            pair_count = len(snapshot.confirmed_pairs)
            status_msg = (
                f"MSM Applied: {context.direction.value} from "
                f"{context.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')} | "
                f"Pairs: {pair_count} | Trend: {snapshot.trend_status}"
            )
            return MSMServiceResult(
                context=context,
                snapshot=snapshot,
                candles=tuple(candles),
                status_message=status_msg,
                candle_count=len(candles),
                start_candle_found=True,
                last_processed_index=snapshot.last_processed_index,
                last_received_index=snapshot.last_processed_index,
                error=None,
            )
    except Exception as e:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(candles),
            status_message=f"MSM calculation error: {e}",
            candle_count=len(candles),
            start_candle_found=True,
            error=str(e),
        )


def is_context_compatible(
    saved_context: Union[MSMContext, Dict[str, Any], None],
    current_source: str,
    current_symbol: Optional[str],
    current_timeframe: str,
) -> bool:
    """Verifies whether a saved MSM configuration matches the current chart context (R10.5).

    Prevents markings from one instrument / timeframe / data source being drawn
    on another.
    """
    if saved_context is None:
        return False

    try:
        if isinstance(saved_context, dict):
            ctx = MSMContext.from_dict(saved_context)
        elif isinstance(saved_context, MSMContext):
            ctx = saved_context
        else:
            return False
    except Exception:
        return False

    if not ctx.enabled:
        return False

    if ctx.rule_version not in SUPPORTED_RULE_VERSIONS:
        return False

    if ctx.data_source.lower() != current_source.lower():
        return False

    if current_symbol is None or ctx.symbol != current_symbol:
        return False

    if ctx.timeframe.upper() != current_timeframe.upper():
        return False

    return True
