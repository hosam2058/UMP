import os

TRADING_PAIR = os.getenv("TRADING_PAIR", "XAUUSD").upper()

PAIRS = {
    "XAUUSD": {
        "token": os.getenv("TRADING_BOT_TOKEN"),
        "display_name": "الذهب",
        "symbol": "XAUUSD",
        "yahoo_symbol": "GC=F",
        "yahoo_symbol_v7": "GC%3DF",
        "ws_symbol": "OANDA:XAU_USD",
        "currency": "$",
        "decimals": 2,
        "min_price": 100.0,
        "db_file": "data/trading_bot.db",
        "is_gold": True,
        "is_24_7": False,
    },
    "BTCUSD": {
        "token": os.getenv("BTCUSD_BOT_TOKEN"),
        "display_name": "البيتكوين",
        "symbol": "BTCUSD",
        "yahoo_symbol": "BTC-USD",
        "yahoo_symbol_v7": "BTC-USD",
        "ws_symbol": "BINANCE:BTCUSDT",
        "currency": "$",
        "decimals": 2,
        "min_price": 1000.0,
        "db_file": "data/btcusd_bot.db",
        "is_gold": False,
        "is_24_7": True,
    },
    "EURUSD": {
        "token": os.getenv("EURUSD_BOT_TOKEN"),
        "display_name": "اليورو/دولار",
        "symbol": "EURUSD",
        "yahoo_symbol": "EURUSD=X",
        "yahoo_symbol_v7": "EURUSD%3DX",
        "ws_symbol": "OANDA:EUR_USD",
        "currency": "",
        "decimals": 5,
        "min_price": 0.5,
        "db_file": "data/eurusd_bot.db",
        "is_gold": False,
        "is_24_7": False,
    },
}

if TRADING_PAIR not in PAIRS:
    raise ValueError(f"TRADING_PAIR غير صالح: {TRADING_PAIR}. الخيارات: {list(PAIRS.keys())}")

PAIR_CFG = PAIRS[TRADING_PAIR]

# ── فحص أمان التوكن ────────────────────────────────────────────
_token_var_map = {
    "XAUUSD": "TRADING_BOT_TOKEN",
    "BTCUSD": "BTCUSD_BOT_TOKEN",
    "EURUSD": "EURUSD_BOT_TOKEN",
}
if not PAIR_CFG["token"]:
    _required_var = _token_var_map[TRADING_PAIR]
    raise RuntimeError(
        f"Environment variable {_required_var} is not defined — add it to Secrets"
    )
