"""Unified Market Data Snapshot for Aladeen / TopG.

Implements the single-fetch architecture with strict snapshot boundary validation:
- Single fetch/load path per market-data event.
- Immutable MarketCandleRecord with lossless preservation of close_time and source IDs.
- Strict pre-coercion type and contract validation (rejects bool/str/inf/NaN).
- Deep immutability and mutation isolation across to_dict() and from_dict().
- Context and request-generation tracking (request_token) for stale response suppression.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from aladeen.data.contract import (
    BarStatus,
    CandleValidationError,
    validate_candle_data,
)
from aladeen.strategy.types import VALID_BAR_STATUSES
from aladeen.data.fixtures import DEMO_SYMBOL, SUPPORTED_TIMEFRAMES, load_fixture
from aladeen.data.mt5_adapter import (
    MT5ConnectionError,
    MT5ConnectionState,
    MT5DataError,
    MT5Error,
    MT5SymbolError,
    get_mt5_adapter,
)
from aladeen.strategy.service import validate_candle_completion


@dataclass(frozen=True)
class MarketCandleRecord:
    """Immutable candle record preserving full market evidence and provenance losslessly."""
    time: str
    open: float
    high: float
    low: float
    close: float
    is_forming: bool
    bar_status: str
    index: Optional[int] = None
    close_time: Optional[str] = None

    def __post_init__(self) -> None:
        # Pre-coercion strict validation (R12.2)
        # 1. Price fields must not be bool, must be finite, strictly positive
        for field_name in ("open", "high", "low", "close"):
            val = getattr(self, field_name)
            if isinstance(val, bool):
                raise TypeError(f"Candle {field_name} must not be boolean, got bool: {val}")
            if not isinstance(val, (int, float, np.integer, np.floating)):
                raise TypeError(f"Candle {field_name} must be numeric, got {type(val).__name__}")
            if not math.isfinite(float(val)):
                raise ValueError(f"Candle {field_name} must be finite, got: {val}")
            if float(val) <= 0.0:
                raise ValueError(f"Candle {field_name} must be strictly positive, got: {val}")

        # 2. OHLC consistency check
        o, h, l, c = float(self.open), float(self.high), float(self.low), float(self.close)
        if h < max(o, c):
            raise ValueError(f"Candle high ({h}) cannot be less than max(open, close) ({max(o, c)})")
        if l > min(o, c):
            raise ValueError(f"Candle low ({l}) cannot be greater than min(open, close) ({min(o, c)})")

        # 3. Completion evidence validation
        if isinstance(self.is_forming, (bool, np.bool_)):
            object.__setattr__(self, "is_forming", bool(self.is_forming))
        else:
            raise TypeError(f"Candle is_forming must be bool, got {type(self.is_forming).__name__}")

        if not isinstance(self.bar_status, str):
            raise TypeError(f"Candle bar_status must be str, got {type(self.bar_status).__name__}")
        if self.bar_status not in VALID_BAR_STATUSES:
            raise ValueError(f"Unknown bar_status '{self.bar_status}'. Must be one of {sorted(VALID_BAR_STATUSES)}")

        if self.is_forming and self.bar_status == "CONFIRMED_COMPLETED":
            raise ValueError("Contradictory completion evidence: is_forming=True cannot have bar_status='CONFIRMED_COMPLETED'")
        if not self.is_forming and self.bar_status in {"UNCONFIRMED_LATEST", "FORMING"}:
            raise ValueError(f"Contradictory completion evidence: is_forming=False cannot have bar_status='{self.bar_status}'")

# 4. Explicit index validation (must not be bool or float)
        if self.index is not None:
            if isinstance(self.index, (bool, np.bool_)):
                raise TypeError(f"Candle index must not be boolean, got bool: {self.index}")
            if not isinstance(self.index, (int, np.integer)):
                raise TypeError(f"Candle index must be integer, got {type(self.index).__name__} ({self.index})")
            object.__setattr__(self, "index", int(self.index))

        # 5. Timestamp validation: strict ISO format and timezone awareness (R13.3)
        if not isinstance(self.time, str) or not self.time:
            raise TypeError(f"Candle time must be non-empty ISO string, got {type(self.time).__name__}")
        try:
            parsed_time = datetime.fromisoformat(self.time)
        except Exception as e:
            raise ValueError(f"Candle time is not a valid ISO timestamp '{self.time}': {e}") from e

        if parsed_time.tzinfo is None or parsed_time.tzinfo.utcoffset(parsed_time) is None:
            raise ValueError(f"Candle time must be timezone-aware (UTC). Naive timestamp rejected: '{self.time}'")

        if self.close_time is not None:
            if not isinstance(self.close_time, str) or not self.close_time:
                raise TypeError(f"Candle close_time must be ISO string if provided, got {type(self.close_time).__name__}")
            try:
                parsed_close = datetime.fromisoformat(self.close_time)
            except Exception as e:
                raise ValueError(f"Candle close_time is not a valid ISO timestamp '{self.close_time}': {e}") from e

            if parsed_close.tzinfo is None or parsed_close.tzinfo.utcoffset(parsed_close) is None:
                raise ValueError(f"Candle close_time must be timezone-aware (UTC). Naive timestamp rejected: '{self.close_time}'")

            if parsed_close <= parsed_time:
                raise ValueError(f"Candle close_time ({self.close_time}) must be strictly later than open time ({self.time})")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize candle record to plain primitive dictionary."""
        d: Dict[str, Any] = {
            "time": self.time,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "is_forming": self.is_forming,
            "bar_status": self.bar_status,
        }
        if self.index is not None:
            d["index"] = self.index
        if self.close_time is not None:
            d["close_time"] = self.close_time
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MarketCandleRecord:
        """Construct and strictly validate MarketCandleRecord from dict."""
        if not isinstance(data, dict):
            raise TypeError(f"Candle record must be dict, got {type(data).__name__}")
        return cls(
            time=data.get("time"),  # type: ignore[arg-type]
            open=data.get("open"),  # type: ignore[arg-type]
            high=data.get("high"),  # type: ignore[arg-type]
            low=data.get("low"),  # type: ignore[arg-type]
            close=data.get("close"),  # type: ignore[arg-type]
            is_forming=data.get("is_forming"),  # type: ignore[arg-type]
            bar_status=data.get("bar_status"),  # type: ignore[arg-type]
            index=data.get("index"),
            close_time=data.get("close_time"),
        )


VALID_FETCH_STATUSES = frozenset({
    "SUCCESS",
    "DISCONNECTED",
    "NO_SYMBOL",
    "CONNECTION_ERROR",
    "DATA_ERROR",
    "VALIDATION_ERROR",
})


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Immutable context-tagged market-data snapshot shared across UI components."""
    revision_id: str
    data_source: str
    symbol: str
    timeframe: str
    candle_count: int
    timestamp_utc: str
    fetch_status: str  # Must be one of VALID_FETCH_STATUSES
    error_message: Optional[str] = None
    broker_connected: bool = False
    request_token: Optional[str] = None
    candles_data: Tuple[MarketCandleRecord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Strict validation of top-level snapshot fields (R12.2, R13.3)
        if not isinstance(self.revision_id, str) or not self.revision_id.strip():
            raise TypeError("revision_id must be a non-empty string")
        if not isinstance(self.data_source, str) or self.data_source not in {"demo", "mt5"}:
            raise ValueError(f"data_source must be 'demo' or 'mt5', got: {self.data_source}")
        if not isinstance(self.symbol, str):
            raise TypeError(f"symbol must be str, got {type(self.symbol).__name__}")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise ValueError(f"timeframe must be non-empty string, got: {self.timeframe}")
        if isinstance(self.candle_count, (bool, np.bool_)) or not isinstance(self.candle_count, (int, np.integer)):
            raise TypeError(f"candle_count must be integer, got {type(self.candle_count).__name__}")
        if self.candle_count < 0:
            raise ValueError(f"candle_count cannot be negative, got {self.candle_count}")
        if not isinstance(self.timestamp_utc, str) or not self.timestamp_utc.strip():
            raise TypeError(f"timestamp_utc must be non-empty string, got {type(self.timestamp_utc).__name__}")
        if not isinstance(self.fetch_status, str) or self.fetch_status not in VALID_FETCH_STATUSES:
            raise ValueError(f"fetch_status must be one of {sorted(VALID_FETCH_STATUSES)}, got: '{self.fetch_status}'")
        if not isinstance(self.broker_connected, bool):
            raise TypeError(f"broker_connected must be bool, got {type(self.broker_connected).__name__}")
        if self.request_token is not None:
            if not isinstance(self.request_token, str) or not self.request_token.strip():
                raise TypeError(f"request_token must be non-empty str if present, got: {self.request_token}")

        # Payload consistency validation (R13.3)
        if self.fetch_status == "SUCCESS":
            if not self.symbol.strip():
                raise ValueError("Successful snapshot must have a non-empty symbol")
            if self.candle_count != len(self.candles_data):
                raise ValueError(
                    f"Candle count mismatch in successful snapshot: header claims {self.candle_count}, "
                    f"but contains {len(self.candles_data)} candle records"
                )
            if self.candle_count == 0:
                raise ValueError("Successful snapshot must contain at least 1 candle record")
            if self.error_message is not None:
                raise ValueError("Successful snapshot must not have an error_message")

            # Source ID (index) uniqueness validation (R14.6: chronology defined by timestamps, source IDs are unique identifiers)
            indices = [c.index for c in self.candles_data if c.index is not None]
            if indices:
                if len(indices) != len(self.candles_data):
                    raise ValueError("Inconsistent source IDs: some candles have an index while others do not")
                if len(set(indices)) != len(indices):
                    raise ValueError("Candle source IDs must be unique; duplicate source IDs detected")
        else:
            if len(self.candles_data) > 0 or self.candle_count > 0:
                raise ValueError(f"Failed snapshot ({self.fetch_status}) must have candle_count=0 and empty candles_data")
            if not isinstance(self.error_message, str) or not self.error_message.strip():
                raise ValueError(f"Failed snapshot ({self.fetch_status}) must have a non-empty error_message")

    @property
    def is_valid(self) -> bool:
        """True if market data was fetched and validated successfully."""
        return self.fetch_status == "SUCCESS" and len(self.candles_data) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize snapshot to dictionary with defensive deep copy (R12.2)."""
        return {
            "revision_id": self.revision_id,
            "data_source": self.data_source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_count": self.candle_count,
            "timestamp_utc": self.timestamp_utc,
            "fetch_status": self.fetch_status,
            "error_message": self.error_message,
            "broker_connected": self.broker_connected,
            "request_token": self.request_token,
            "candles_data": [copy.deepcopy(c.to_dict()) for c in self.candles_data],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MarketDataSnapshot:
        """Construct MarketDataSnapshot with strict deserialization validation (R12.2, R13.3)."""
        if not isinstance(data, dict):
            raise TypeError(f"Snapshot data must be dict, got {type(data).__name__}")

        raw_candles = data.get("candles_data", [])
        if not isinstance(raw_candles, (list, tuple)):
            raise TypeError(f"candles_data must be list or tuple, got {type(raw_candles).__name__}")

        parsed_candles = []
        for i, item in enumerate(raw_candles):
            if isinstance(item, MarketCandleRecord):
                parsed_candles.append(item)
            elif isinstance(item, dict):
                parsed_candles.append(MarketCandleRecord.from_dict(item))
            else:
                raise TypeError(f"Candle record at position {i} must be dict or MarketCandleRecord, got {type(item).__name__}")

        snap = cls(
            revision_id=data.get("revision_id", ""),
            data_source=data.get("data_source", "demo"),
            symbol=data.get("symbol", ""),
            timeframe=data.get("timeframe", "H4"),
            candle_count=data.get("candle_count", 0),
            timestamp_utc=data.get("timestamp_utc", ""),
            fetch_status=data.get("fetch_status", "DISCONNECTED"),
            error_message=data.get("error_message"),
            broker_connected=data.get("broker_connected", False),
            request_token=data.get("request_token"),
            candles_data=tuple(parsed_candles),
        )

        if snap.fetch_status == "SUCCESS":
            # Shared contract validation on deserialized data (R13.3)
            df = snap.to_dataframe()
            validate_candle_data(df)

        return snap

    def to_dataframe(self) -> pd.DataFrame:
        """Convert serialized candle records back to contract-compliant DataFrame."""
        if not self.candles_data:
            empty = pd.DataFrame(columns=["open", "high", "low", "close", "is_forming", "bar_status"])
            empty.index = pd.DatetimeIndex([], tz="UTC")
            return empty

        rows = [c.to_dict() for c in self.candles_data]
        df = pd.DataFrame(rows)
        # Parse timestamps without silently coercing naive strings (R13.3)
        df["time"] = pd.to_datetime(df["time"])
        if df["time"].dt.tz is None:
            raise CandleValidationError("Candle timestamps must be timezone-aware. Naive timestamps rejected.")
        df["time"] = df["time"].dt.tz_convert("UTC")
        df = df.set_index("time")
        return df


_revision_counter = 0


def _generate_revision_id() -> str:
    global _revision_counter
    _revision_counter += 1
    return f"rev-{time.time_ns()}-{_revision_counter}"


def fetch_market_snapshot(
    data_source: str,
    symbol: str | None,
    timeframe: str,
    candle_count: int,
    is_connected: bool,
    adapter: Any = None,
    current_state: str | None = None,
    request_token: str | None = None,
) -> Tuple[MarketDataSnapshot, Optional[dict]]:
    """Single unified fetch/load path per market-data update.

    Returns:
    --------
    Tuple[MarketDataSnapshot, Optional[dict]]
        The coherent market data snapshot, and an optional loss_trigger dict
        if a connection loss or state change occurred during fetch.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rev_id = _generate_revision_id()

    if adapter is None:
        adapter = get_mt5_adapter()

    # ------------------- DEMO MODE -------------------
    if data_source == "demo":
        active_sym = DEMO_SYMBOL
        if timeframe not in SUPPORTED_TIMEFRAMES:
            return MarketDataSnapshot(
                revision_id=rev_id,
                data_source="demo",
                symbol=active_sym,
                timeframe=timeframe,
                candle_count=0,
                timestamp_utc=now_utc,
                fetch_status="DATA_ERROR",
                error_message=f"Timeframe '{timeframe}' is not available in demo mode. Supported: {', '.join(SUPPORTED_TIMEFRAMES)}.",
                request_token=request_token,
            ), None

        df = load_fixture(DEMO_SYMBOL, timeframe)
        if df is None or df.empty:
            return MarketDataSnapshot(
                revision_id=rev_id,
                data_source="demo",
                symbol=active_sym,
                timeframe=timeframe,
                candle_count=0,
                timestamp_utc=now_utc,
                fetch_status="DATA_ERROR",
                error_message=f"No demo data available for {DEMO_SYMBOL} on {timeframe}.",
                request_token=request_token,
            ), None

        # Verify full candle contract before proceeding (R12.2)
        try:
            validate_candle_data(df)
        except Exception as e:
            return MarketDataSnapshot(
                revision_id=rev_id,
                data_source="demo",
                symbol=active_sym,
                timeframe=timeframe,
                candle_count=0,
                timestamp_utc=now_utc,
                fetch_status="VALIDATION_ERROR",
                error_message=f"Candle data contract violation: {e}",
                request_token=request_token,
            ), None

        # Fail-closed completion validation & lossless preservation (R12.2)
        records: List[MarketCandleRecord] = []
        for row_pos, (ts, row) in enumerate(df.iterrows()):
            try:
                is_forming, bar_status = validate_candle_completion(row_pos, row)
                close_time_val = None
                if "close_time" in row and pd.notna(row["close_time"]):
                    ct = row["close_time"]
                    close_time_val = ct.isoformat() if hasattr(ct, "isoformat") else str(ct)

                idx_val = None
                if "index" in row and pd.notna(row["index"]):
                    idx_raw = row["index"]
                    if isinstance(idx_raw, (bool, np.bool_)):
                        raise TypeError(f"Explicit index at row {row_pos} must not be boolean, got bool: {idx_raw}")
                    if not isinstance(idx_raw, (int, np.integer)):
                        raise TypeError(f"Explicit index at row {row_pos} must be integer type, got {type(idx_raw).__name__} ({idx_raw})")
                    idx_val = int(idx_raw)

                rec = MarketCandleRecord(
                    time=ts.isoformat(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    is_forming=is_forming,
                    bar_status=bar_status,
                    index=idx_val,
                    close_time=close_time_val,
                )
                records.append(rec)
            except Exception as e:
                return MarketDataSnapshot(
                    revision_id=rev_id,
                    data_source="demo",
                    symbol=active_sym,
                    timeframe=timeframe,
                    candle_count=0,
                    timestamp_utc=now_utc,
                    fetch_status="VALIDATION_ERROR",
                    error_message=f"Candle validation failed at row {row_pos}: {e}",
                    request_token=request_token,
                ), None

        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="demo",
            symbol=active_sym,
            timeframe=timeframe,
            candle_count=len(records),
            timestamp_utc=now_utc,
            fetch_status="SUCCESS",
            error_message=None,
            broker_connected=False,
            request_token=request_token,
            candles_data=tuple(records),
        ), None

    # ------------------- MT5 MODE -------------------
    if not is_connected:
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol or "",
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="DISCONNECTED",
            error_message="MT5 terminal is not connected. Click '⚡ Connect MT5' to load data.",
            request_token=request_token,
        ), None

    if not symbol:
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol="",
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="NO_SYMBOL",
            error_message="No symbol selected. Please select a valid symbol from MT5 MarketWatch.",
            request_token=request_token,
        ), None

    try:
        df = adapter.fetch_candles(symbol, timeframe, count=candle_count)
        broker_conn = adapter.is_broker_connected()

        # Verify full candle contract before proceeding (R12.2)
        try:
            validate_candle_data(df)
        except Exception as e:
            return MarketDataSnapshot(
                revision_id=rev_id,
                data_source="mt5",
                symbol=symbol,
                timeframe=timeframe,
                candle_count=0,
                timestamp_utc=now_utc,
                fetch_status="VALIDATION_ERROR",
                error_message=f"Candle data contract violation: {e}",
                broker_connected=broker_conn,
                request_token=request_token,
            ), None

        # Fail-closed completion validation & lossless preservation (R12.2)
        records = []
        for row_pos, (ts, row) in enumerate(df.iterrows()):
            try:
                is_forming, bar_status = validate_candle_completion(row_pos, row)
                close_time_val = None
                if "close_time" in row and pd.notna(row["close_time"]):
                    ct = row["close_time"]
                    close_time_val = ct.isoformat() if hasattr(ct, "isoformat") else str(ct)

                idx_val = None
                if "index" in row and pd.notna(row["index"]):
                    idx_raw = row["index"]
                    if isinstance(idx_raw, (bool, np.bool_)):
                        raise TypeError(f"Explicit index at row {row_pos} must not be boolean, got bool: {idx_raw}")
                    if not isinstance(idx_raw, (int, np.integer)):
                        raise TypeError(f"Explicit index at row {row_pos} must be integer type, got {type(idx_raw).__name__} ({idx_raw})")
                    idx_val = int(idx_raw)

                rec = MarketCandleRecord(
                    time=ts.isoformat(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    is_forming=is_forming,
                    bar_status=bar_status,
                    index=idx_val,
                    close_time=close_time_val,
                )
                records.append(rec)
            except Exception as e:
                return MarketDataSnapshot(
                    revision_id=rev_id,
                    data_source="mt5",
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_count=0,
                    timestamp_utc=now_utc,
                    fetch_status="VALIDATION_ERROR",
                    error_message=f"Candle validation failed at row {row_pos}: {e}",
                    broker_connected=broker_conn,
                    request_token=request_token,
                ), None

        # Detect broker state change or disconnection
        new_state = adapter.get_connection_state().value
        loss_trigger = None
        if current_state and new_state != current_state:
            if new_state == MT5ConnectionState.DISCONNECTED.value:
                loss_trigger = {"type": "connection_loss", "error": "Terminal disconnected", "timestamp": now_utc}
            else:
                loss_trigger = {"type": "state_change", "new_state": new_state, "timestamp": now_utc}
        elif new_state == MT5ConnectionState.DISCONNECTED.value:
            loss_trigger = {"type": "connection_loss", "error": "Terminal disconnected", "timestamp": now_utc}

        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=len(records),
            timestamp_utc=now_utc,
            fetch_status="SUCCESS",
            error_message=None,
            broker_connected=broker_conn,
            request_token=request_token,
            candles_data=tuple(records),
        ), loss_trigger

    except MT5ConnectionError as e:
        # Note: Do not disconnect shared adapter here; stale-capable fetch work must not disconnect newer sessions (R14.2)
        loss_trigger = {"type": "connection_loss", "error": str(e), "timestamp": now_utc}
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="CONNECTION_ERROR",
            error_message=f"Connection Lost: {e}",
            broker_connected=False,
            request_token=request_token,
        ), loss_trigger

    except MT5SymbolError as e:
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="DATA_ERROR",
            error_message=f"Symbol Error: {e}",
            broker_connected=False,
            request_token=request_token,
        ), None

    except MT5DataError as e:
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="DATA_ERROR",
            error_message=f"Fetch Failed: {e}",
            broker_connected=False,
            request_token=request_token,
        ), None

    except CandleValidationError as e:
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="VALIDATION_ERROR",
            error_message=f"Data Contract Violation: {e}",
            broker_connected=False,
            request_token=request_token,
        ), None

    except Exception as e:
        return MarketDataSnapshot(
            revision_id=rev_id,
            data_source="mt5",
            symbol=symbol,
            timeframe=timeframe,
            candle_count=0,
            timestamp_utc=now_utc,
            fetch_status="DATA_ERROR",
            error_message=f"Unexpected Error: {e}",
            broker_connected=False,
            request_token=request_token,
        ), None
