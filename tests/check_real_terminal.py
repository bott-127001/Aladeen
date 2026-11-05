import sys
from aladeen.data.mt5_adapter import MT5Adapter, MT5ConnectionState
from aladeen.data.contract import validate_candle_data, BarStatus

def test_real_terminal():
    adapter = MT5Adapter()
    print("Testing real terminal connection...")
    state = adapter.connect()
    print(f"Connection state: {state.name}")
    assert adapter.is_connected() is True
    assert adapter.get_connection_state() in (MT5ConnectionState.CONNECTED_TO_BROKER, MT5ConnectionState.TERMINAL_ONLY)

    symbols = adapter.get_symbols()
    print(f"Total symbols returned: {len(symbols)}")
    target_sym = "EURUSD" if "EURUSD" in symbols else (symbols[0] if symbols else None)
    if not target_sym:
        print("No symbols available in terminal.")
        adapter.disconnect()
        sys.exit(1)

    print(f"Fetching 10 H1 candles for {target_sym}...")
    df = adapter.fetch_candles(target_sym, "H1", 10)
    print(f"Fetched {len(df)} candles.")
    
    # Contract validation
    valid_df = validate_candle_data(df)
    assert len(valid_df) == len(df)
    print("Candle contract validation PASSED!")

    # Completion / forming semantics check
    assert "is_forming" in valid_df.columns
    assert "bar_status" in valid_df.columns
    assert bool(valid_df["is_forming"].iloc[-1]) is True
    assert valid_df["bar_status"].iloc[-1] == BarStatus.UNCONFIRMED_LATEST.value
    if len(valid_df) > 1:
        assert bool(valid_df["is_forming"].iloc[-2]) is False
        assert valid_df["bar_status"].iloc[-2] == BarStatus.CONFIRMED_COMPLETED.value
    print("Candle bar completion semantics verified on live data!")

    # Disconnect & idempotent cleanup
    adapter.disconnect()
    assert adapter.is_connected() is False
    assert adapter.get_connection_state() == MT5ConnectionState.DISCONNECTED
    adapter.disconnect()  # Second disconnect must be idempotent
    print("Disconnect and idempotent cleanup PASSED!")

if __name__ == "__main__":
    test_real_terminal()
