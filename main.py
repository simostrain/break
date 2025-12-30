import requests
import time
from datetime import datetime, timezone

# Test with these 4 coins
TEST_SYMBOLS = ["MantaUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT"]
BINANCE_API = "https://api.binance.com"

session = requests.Session()

def calculate_atr_rma(candles, current_index, period=10):
    """
    Calculate ATR using RMA (same as Pine Script atr() function)
    """
    if current_index < period:
        return None
    
    # Calculate all TRs
    trs = []
    for i in range(1, current_index + 1):
        high = float(candles[i][2])
        low = float(candles[i][3])
        prev_close = float(candles[i-1][4])
        
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    
    # First ATR is SMA
    atr = sum(trs[:period]) / period
    
    # Then use RMA (Wilder's smoothing)
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    
    return atr

def calculate_supertrend(candles, current_index, atr_period=10, multiplier=3.0):
    """
    Calculate Supertrend - Direct translation from Pine Script by kivancOzbilgic
    Source: https://stackoverflow.com/a/78996666
    Posted by Muhammad Saqib Scientist
    Retrieved 2025-12-30, License - CC BY-SA 4.0
    
    Returns: (supertrend_value, direction, upper_band, lower_band)
    direction = 1 for uptrend, -1 for downtrend
    """
    if current_index < atr_period:
        return None, None, None, None
    
    # Arrays to store values
    up_list = []
    dn_list = []
    trend_list = []
    atr_list = []
    
    # Calculate from atr_period to current_index
    for idx in range(atr_period, current_index + 1):
        # Get current candle
        high = float(candles[idx][2])
        low = float(candles[idx][3])
        close = float(candles[idx][4])
        
        # src = hl2
        src = (high + low) / 2
        
        # Calculate ATR using RMA
        atr = calculate_atr_rma(candles, idx, atr_period)
        atr_list.append(atr)
        
        # up = src - (Multiplier * atr)
        up = src - (multiplier * atr)
        
        # up1 = nz(up[1], up)
        up1 = up_list[-1] if len(up_list) > 0 else up
        
        # Get previous close
        prev_close = float(candles[idx-1][4]) if idx > 0 else close
        
        # up := close[1] > up1 ? max(up, up1) : up
        if prev_close > up1:
            up = max(up, up1)
        
        up_list.append(up)
        
        # dn = src + (Multiplier * atr)
        dn = src + (multiplier * atr)
        
        # dn1 = nz(dn[1], dn)
        dn1 = dn_list[-1] if len(dn_list) > 0 else dn
        
        # dn := close[1] < dn1 ? min(dn, dn1) : dn
        if prev_close < dn1:
            dn = min(dn, dn1)
        
        dn_list.append(dn)
        
        # Determine trend
        if idx == atr_period:
            # trend = 1 (start with uptrend)
            trend = 1
        else:
            prev_trend = trend_list[-1]
            prev_up = up_list[-2]
            prev_dn = dn_list[-2]
            
            # trend := trend == -1 and close > dn1 ? 1 : trend == 1 and close < up1 ? -1 : trend
            if prev_trend == -1 and close > prev_dn:
                trend = 1  # Switch to uptrend
            elif prev_trend == 1 and close < prev_up:
                trend = -1  # Switch to downtrend
            else:
                trend = prev_trend  # Stay in same trend
        
        trend_list.append(trend)
    
    # Return last values
    last_trend = trend_list[-1]
    last_up = up_list[-1]
    last_dn = dn_list[-1]
    
    if last_trend == 1:
        # Uptrend: supertrend = up, resistance = dn
        return last_up, last_trend, last_dn, last_up
    else:
        # Downtrend: supertrend = dn, support = up
        return last_dn, last_trend, last_dn, last_up

def test_supertrend():
    print("="*80)
    print("SUPERTREND TEST - Compare with Binance")
    print("="*80)
    print("\nFetching latest candles for 4 coins...\n")
    
    for symbol in TEST_SYMBOLS:
        try:
            # Fetch 50 hourly candles
            url = f"{BINANCE_API}/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
            candles = session.get(url, timeout=60).json()
            
            if not candles or isinstance(candles, dict):
                print(f"{symbol}: Error fetching data")
                continue
            
            # Get the latest COMPLETED candle (second to last)
            current_index = len(candles) - 2
            
            # Get candle info
            candle = candles[current_index]
            candle_time = datetime.fromtimestamp(candle[0]/1000, tz=timezone.utc)
            open_price = float(candle[1])
            high = float(candle[2])
            low = float(candle[3])
            close = float(candle[4])
            hl2 = (high + low) / 2
            
            # Calculate Supertrend with debug info
            st_value, direction, upper_band, lower_band = calculate_supertrend(candles, current_index)
            
            # Also calculate ATR separately for display
            all_trs = []
            for i in range(1, current_index + 1):
                h = float(candles[i][2])
                l = float(candles[i][3])
                pc = float(candles[i-1][4])
                tr = max(h - l, abs(h - pc), abs(l - pc))
                all_trs.append(tr)
            
            # Calculate current ATR
            atr_period = 10
            if current_index >= atr_period:
                # First ATR
                first_atr = sum(all_trs[:atr_period]) / atr_period
                # Current ATR (RMA)
                current_atr = first_atr
                for i in range(atr_period, current_index):
                    current_atr = ((current_atr * (atr_period - 1)) + all_trs[i]) / atr_period
            else:
                current_atr = None
            
            if st_value is None:
                print(f"{symbol}: Not enough data")
                continue
            
            # Determine trend name
            if direction == 1:
                trend_name = "UPTREND 🟢"
                support = st_value
                resistance = upper_band
            else:
                trend_name = "DOWNTREND 🔴"
                support = lower_band
                resistance = st_value
            
            # Print results
            print(f"{'='*80}")
            print(f"Symbol: {symbol}")
            print(f"Time:   {candle_time.strftime('%Y-%m-%d %H:%M')} UTC")
            print(f"{'='*80}")
            print(f"High:       ${high:.8f}")
            print(f"Low:        ${low:.8f}")
            print(f"Close:      ${close:.8f}")
            print(f"HL2:        ${hl2:.8f}")
            if current_atr:
                print(f"ATR:        ${current_atr:.8f}")
            print(f"Trend:      {trend_name}")
            print(f"-"*80)
            print(f"Supertrend: ${st_value:.8f}")
            print(f"Upper Band: ${upper_band:.8f}")
            print(f"Lower Band: ${lower_band:.8f}")
            
            # Calculate distances
            if direction == 1:  # Uptrend
                dist_to_support = ((close - support) / support) * 100
                dist_to_resistance = ((resistance - close) / close) * 100
                print(f"-"*80)
                print(f"Distance to Support:    +{dist_to_support:.2f}%")
                print(f"Distance to Resistance: +{dist_to_resistance:.2f}%")
            else:  # Downtrend
                dist_to_resistance = ((close - resistance) / resistance) * 100
                dist_to_support = ((support - close) / close) * 100
                print(f"-"*80)
                print(f"Distance to Resistance: {dist_to_resistance:.2f}%")
                print(f"Distance to Support:    +{dist_to_support:.2f}%")
            
            print()
            
        except Exception as e:
            print(f"{symbol}: Error - {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print("="*80)
    print("Compare these values with Binance chart:")
    print("1. Open Binance")
    print("2. Select 1H timeframe")
    print("3. Add Supertrend indicator (ATR: 10, Factor: 3.0)")
    print("4. Check the latest COMPLETED candle values")
    print("\nExpected Binance values:")
    print("  BTC: 88441.11")
    print("  ETH: 2981.7")
    print("  BNB: 860.45")
    print("  ADA: 0.3602")
    print("="*80)

if __name__ == "__main__":
    test_supertrend()
