"""Unified Market Data Snapshot for Aladeen / TopG.

Implements the single-fetch architecture required by Perplexity review:
- Single fetch/load path per market-data event.
- Context-tagged with revision ID, data source, symbol, timeframe, timestamp.
- Strict fail-closed completion validation (surfacing invalid evidence immediately).
- Shared across chart rendering, starting-candle dropdown options, and MSM inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from aladeen.data.contract import CandleValidationError
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
class MarketDataSnapshot:
    """Immutable context-tagged market-data snapshot shared across UI components."""
    revision_id: str
    data_source: str
    symbol: str
    timeframe: str
    candle_count: int
    timestamp_utc: str
    fetch_status: str  # "SUCCESS", "DISCONNECTED", "NO_SYMBOL", "CONNECTION_ERROR", "DATA_ERROR", "VALIDATION_ERROR"
    error_message: Optional[str] = None
    broker_connected: bool = False
    candles_data: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        """True if market data was fetched and validated successfully."""
        return self.fetch_status == "SUCCESS" and len(self.candles_data) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize snapshot to dictionary for Dash dcc.Store."""
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
            "candles_data": list(self.candles_data),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MarketDataSnapshot:
        """Construct MarketDataSnapshot from dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"data must be dict, got {type(data).__name__}")
        return cls(
            revision_id=str(data.get("revision_id", "")),
            data_source=str(data.get("data_source", "demo")),
            symbol=str(data.get("symbol", "")),
            timeframe=str(data.get("timeframe", "H4")),
            candle_count=int(data.get("candle_count", 0)),
            timestamp_utc=str(data.get("timestamp_utc", "")),
            fetch_status=str(data.get("fetch_status", "DISCONNECTED")),
            error_message=data.get("error_message"),
            broker_connected=bool(data.get("broker_connected", False)),
            candles_data=tuple(data.get("candles_data", [])),
        )

    def to_dataframe(self) -> pd.DataFrame:
        """Convert serialized candle records back to contract-compliant DataFrame."""
        if not self.candles_data:
            empty = pd.DataFrame(columns=["open", "high", "low", "close", "is_forming", "bar_status"])
            empty.index = pd.DatetimeIndex([], tz="UTC")
            return empty

        df = pd.DataFrame(list(self.candles_data))
        df["time"] = pd.to_datetime(df["time"], utc=True)
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
) -> Tuple[MarketDataSnapshot, Optional[dict]]:
    """Single unified fetch/load path per market-data update.

    Returns:
    --------
    Tuple[MarketDataSnapshot, Optional[dict]]
        The coherent market data snapshot, and an optional loss_trigger dict
        if a connection loss occurred during fetch.
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
            ), None

        # Fail-closed completion validation (R10.1 & item 4)
        records = []
        for row_pos, (ts, row) in enumerate(df.iterrows()):
            try:
                is_forming, bar_status = validate_candle_completion(row_pos, row)
            except Exception as e:
                return MarketDataSnapshot(
                    revision_id=rev_id,
                    data_source="demo",
                    symbol=active_sym,
                    timeframe=timeframe,
                    candle_count=0,
                    timestamp_utc=now_utc,
                    fetch_status="VALIDATION_ERROR",
                    error_message=f"Completion validation failed at row {row_pos}: {e}",
                ), None

            rec = {
                "time": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "is_forming": is_forming,
                "bar_status": bar_status,
            }
            if "index" in row and pd.notna(row["index"]):
                rec["index"] = int(row["index"])
            records.append(rec)

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
        ), None

    try:
        df = adapter.fetch_candles(symbol, timeframe, count=candle_count)
        broker_conn = adapter.is_broker_connected()

        # Fail-closed completion validation (R10.1 & item 4)
        records = []
        for row_pos, (ts, row) in enumerate(df.iterrows()):
            try:
                is_forming, bar_status = validate_candle_completion(row_pos, row)
            except Exception as e:
                return MarketDataSnapshot(
                    revision_id=rev_id,
                    data_source="mt5",
                    symbol=symbol,
                    timeframe=timeframe,
                    candle_count=0,
                    timestamp_utc=now_utc,
                    fetch_status="VALIDATION_ERROR",
                    error_message=f"Completion validation failed at row {row_pos}: {e}",
                    broker_connected=broker_conn,
                ), None

            rec = {
                "time": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "is_forming": is_forming,
                "bar_status": bar_status,
            }
            if "index" in row and pd.notna(row["index"]):
                rec["index"] = int(row["index"])
            records.append(rec)

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
            candles_data=tuple(records),
        ), loss_trigger

    except MT5ConnectionError as e:
        adapter.disconnect()
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
        ), None
