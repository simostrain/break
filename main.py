import os
import time
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

# ==== Settings ====
BINANCE_API = "https://api.binance.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RSI_PERIOD = 14
SUPERTREND_LEN = 10
SUPERTREND_MULT = 3

SUPPORT_MIN = 0.0
SUPPORT_MAX = 3.0

reported = set()

CUSTOM_TICKERS = [
    "BTC","ETH","BNB","SOL","XRP","ADA","AVAX","LINK","DOT","MATIC",
    "OP","ARB","ATOM","NEAR","FIL","ICP","AAVE","UNI","SUI","SEI",
    "TRX","LTC","ETC","DOGE","SHIB","TON","APT","INJ","RUNE","KAS",
    "ZRO","ZK","TIA","JUP","WLD","PEPE","PYTH","ORDI","RNDR","GALA"
]

# ==== Session ====
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=2)
session.mount("https://", adapter)

# ==== Telegram ====
def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=30
        )
    except Exception as e:
        print("Telegram error:", e)

# ==== Utils ====
def format_volume(v):
    return f"{v/1_000_000:.2f}M"

def get_binance_server_time():
    try:
        return session.get(f"{BINANCE_API}/api/v3/time", timeout=30).json()["serverTime"] / 1000
    except:
        return time.time()

# ==== RSI ====
def calculate_rsi_with_full_history(closes, period=14):
    if len(closes) < period + 1:
        return None

    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

# ==== BINANCE / TRADINGVIEW SUPERTREND ====
def calculate_supertrend_binance(candles, index):
    if index < SUPERTREND_LEN:
        return None, None, None, None

    df = pd.DataFrame({
        "high":  [float(c[2]) for c in candles[:index+1]],
        "low":   [float(c[3]) for c in candles[:index+1]],
        "close": [float(c[4]) for c in candles[:index+1]],
    })

    st = df.ta.supertrend(length=SUPERTREND_LEN, multiplier=SUPERTREND_MULT)
    if st is None or st.empty:
        return None, None, None, None

    s = f"{SUPERTREND_LEN}_{float(SUPERTREND_MULT)}"

    return (
        st[f"SUPERT_{s}"].iloc[-1],   # active line
        st[f"SUPERTd_{s}"].iloc[-1],  # -1 up | 1 down
        st[f"SUPERTu_{s}"].iloc[-1],  # resistance
        st[f"SUPERTl_{s}"].iloc[-1],  # support
    )

# ==== Binance ====
def get_usdt_pairs():
    wanted = [t.upper() + "USDT" for t in CUSTOM_TICKERS]
    try:
        info = session.get(f"{BINANCE_API}/api/v3/exchangeInfo", timeout=30).json()
        valid = {s["symbol"] for s in info["symbols"]
                 if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"}
        pairs = [s for s in wanted if s in valid]
        print(f"Loaded {len(pairs)} pairs")
        return pairs
    except Exception as e:
        print("Exchange info error:", e)
        return []

def fetch_support_touch(symbol, now_utc, start_time):
    try:
        candles = session.get(
            f"{BINANCE_API}/api/v3/klines?symbol={symbol}&interval=1h&limit=200",
            timeout=30
        ).json()

        if not candles or isinstance(candles, dict):
            return []

        results = []

        for i in range(1, len(candles)-1):
            candle_time = datetime.fromtimestamp(candles[i][0]/1000, tz=timezone.utc)
            if candle_time < start_time or candle_time >= now_utc - timedelta(hours=1):
                continue

            close = float(candles[i][4])
            prev_close = float(candles[i-1][4])
            pct = (close - prev_close) / prev_close * 100

            volume = float(candles[i][5])
            vol_usdt = volume * float(candles[i][1])

            ma_vol = [
                float(candles[j][1]) * float(candles[j][5])
                for j in range(max(0, i-19), i+1)
            ]
            vm = vol_usdt / (sum(ma_vol)/len(ma_vol))

            closes = [float(candles[j][4]) for j in range(i+1)]
            rsi = calculate_rsi_with_full_history(closes)

            st, direction, upper, lower = calculate_supertrend_binance(candles, i)
            if direction != -1:
                continue

            dist_sup = (close - lower) / lower * 100
            if SUPPORT_MIN <= dist_sup <= SUPPORT_MAX:
                hour = candle_time.strftime("%Y-%m-%d %H:00")
                dist_res = (upper - close) / close * 100

                results.append((
                    symbol, pct, close, vol_usdt, vm, rsi,
                    lower, dist_sup, upper, dist_res, hour
                ))

        return results
    except Exception as e:
        print(symbol, e)
        return []

def check_support_touches(symbols):
    now_utc = datetime.now(timezone.utc)
    start_time = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    all_hits = []
    with ThreadPoolExecutor(max_workers=40) as ex:
        futures = [ex.submit(fetch_support_touch, s, now_utc, start_time) for s in symbols]
        for f in as_completed(futures):
            all_hits.extend(f.result())

    return all_hits

def format_report(rows, duration):
    if not rows:
        return None

    grouped = defaultdict(list)
    for r in rows:
        grouped[r[-1]].append(r)

    msg = f"📍 <b>SUPERTREND SUPPORT TOUCH</b>\n⏱ {duration:.2f}s\n\n"

    for hour in sorted(grouped):
        msg += f"⏰ {hour} UTC\n"
        for s,p,c,v,vm,r,sl,ds,rl,dr,h in sorted(grouped[hour], key=lambda x: x[7]):
            sym = s.replace("USDT","")
            msg += (
                f"🎯 <code>{sym:5s} {p:5.2f}% RSI:{r:5.1f} VM:{vm:4.1f}</code>\n"
                f"   🟢 Sup {sl:.5f} (+{ds:.2f}%)\n"
                f"   🔴 Res {rl:.5f} (🎯+{dr:.2f}%)\n\n"
            )

    return msg

# ==== MAIN ====
def main():
    symbols = get_usdt_pairs()
    if not symbols:
        return

    while True:
        start = time.time()
        hits = check_support_touches(symbols)
        duration = time.time() - start

        fresh = []
        for h in hits:
            key = (h[0], h[-1])
            if key not in reported:
                reported.add(key)
                fresh.append(h)

        if fresh:
            msg = format_report(fresh, duration)
            if msg:
                print(msg)
                send_telegram(msg[:4096])
        else:
            print("No signals")

        server = get_binance_server_time()
        sleep = max(0, (server//3600 + 1)*3600 - server + 1)
        time.sleep(sleep)

if __name__ == "__main__":
    main()
