import os

TRADING_PAIR = os.getenv("TRADING_PAIR", "XAUUSD").upper()

PAIRS = {
    "XAUUSD": {
        "token": os.getenv("TRADING_BOT_TOKEN", "8543638509:AAGu_lP83It50LcIXbtZeaC5stuqz5HvHn4"),
        "display_name": "الذهب",
        "symbol": "XAUUSD",
        "yahoo_symbol": "GC=F",
        "yahoo_symbol_v7": "GC%3DF",
        "ws_symbol": "OANDA:XAU_USD",
        "currency": "$",
        "decimals": 2,
        "min_price": 100.0,
        "db_file": "data/trading_bot.db",  # الملف الأصلي — لا تغيّر هذا
        "is_gold": True,
    },
    "BTCUSD": {
        "token": os.getenv("BTCUSD_BOT_TOKEN", "8515228176:AAEaXyMxXT0tS8h4QUjSQJh1mXHLEI-kaVI"),
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
    },
    "EURUSD": {
        "token": os.getenv("EURUSD_BOT_TOKEN", "8385015566:AAHzlqBKey9_Wz4ktgeZudZchUGCL6e0RBQ"),
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
    },
}

if TRADING_PAIR not in PAIRS:
    raise ValueError(f"TRADING_PAIR غير صالح: {TRADING_PAIR}. الخيارات: {list(PAIRS.keys())}")

PAIR_CFG = PAIRS[TRADING_PAIR]
