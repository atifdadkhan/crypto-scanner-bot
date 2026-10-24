import os
import json
import ccxt
import pandas as pd
import ta
import threading
import asyncio
import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# ==========================================
# 1. CONFIGURATION
# ==========================================
TELEGRAM_TOKEN = "8664137345:AAF7ROx4_6PSTHYPKop-Ytf73CQB2Ekw_2g" 
ADMIN_ID = 6620183989 

STATE_FILE = "trades.json"
exchange = ccxt.bitget() 

# 🏆 TOP 30 STRONG CRYPTO COINS
top_30_coins = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'MATIC/USDT',
    'NEAR/USDT', 'INJ/USDT', 'SUI/USDT', 'OP/USDT', 'ARB/USDT',
    'DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'WIF/USDT', 'BONK/USDT',
    'TIA/USDT', 'FET/USDT', 'RNDR/USDT', 'TAO/USDT', 'APT/USDT',
    'FIL/USDT', 'ATOM/USDT', 'IMX/USDT', 'STX/USDT', 'RUNE/USDT'
]

tracked_coins = top_30_coins 
timeframes = ['1h', '4h'] 

# Toggles
FILTER_CORE = True
FILTER_MTF = True
FILTER_VOLUME = True
FILTER_RSI = True

# 🏆 PROFESSIONAL SETTINGS 🏆
# MAX_ACTIVE_TRADES hata diya gaya hai
ATR_MULTIPLIER = 1.5     
MIN_SL_PERCENTAGE = 0.01 

# Global Locks
is_scanning = False 

# Helper function for formatting prices correctly
def fmt(price):
    if price < 0.01: return f"{price:.8f}"
    elif price < 1: return f"{price:.6f}"
    else: return f"{price:.4f}"

# ==========================================
# 2. SESSION FILTER FUNCTION
# ==========================================
def is_trading_session():
    now_utc = datetime.datetime.utcnow()
    current_hour = now_utc.hour
    if 7 <= current_hour < 20:
        return True
    return False

# ==========================================
# 3. FLASK WEB SERVER (Keep-Alive)
# ==========================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 4. STATE MANAGEMENT
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception:
        pass

active_trades = load_state()

# ==========================================
# 5. ERROR HANDLER
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"⚠️ Global Error: {context.error}")

# ==========================================
# 6. TELEGRAM UI HELPERS
# ==========================================
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Active Trades", callback_data='active_trades'), 
         InlineKeyboardButton("🌐 Market Summary", callback_data='market_summary')],
        [InlineKeyboardButton("🔎 Scan Top 30 Coins", callback_data='scan_menu')],
        [InlineKeyboardButton("🔍 Analyze Coin", callback_data='analyze_coin')],
        [InlineKeyboardButton("📊 Manage Coins", callback_data='manage_coins')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings'), 
         InlineKeyboardButton("🔄 System Controls", callback_data='sys_controls')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]
    text = (
        "💼 <b>PRO TRADING TERMINAL</b> 💼\n\n"
        "Welcome Boss! Main aapka personal trading assistant hoon.\n"
        "🛡️ <i>Whale Protection Active</i>\n"
        "🕒 <i>Session: 12 PM - 1 AM (PKT)</i>\n"
        "📊 <i>Tracking Top 30 Coins</i>"
    )
    return text, InlineKeyboardMarkup(keyboard)

def get_scan_menu():
    keyboard = [
        [InlineKeyboardButton("⚡ Scan 15m (Checks 1h)", callback_data='scan_tf_15m')],
        [InlineKeyboardButton("⚡ Scan 1h (Checks 4h)", callback_data='scan_tf_1h')],
        [InlineKeyboardButton("⚡ Scan 4h (Checks 1d)", callback_data='scan_tf_4h')],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
    ]
    text = "🔎 <b>MARKET SCANNER</b>\n\nSelect Timeframe for Top 30 Scan (Pairwise MTF will apply):"
    return text, InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ <b>Access Denied.</b>\nThis is a private bot.", parse_mode='HTML')
        return
    text, reply_markup = get_main_menu()
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

# ==========================================
# 7. BACKGROUND MARKET SCANNER LOGIC
# ==========================================
def run_market_scan(scan_mode, scan_tf):
    try:
        results = []
        scanned_names = []
        
        for coin in top_30_coins:
            scanned_names.append(coin.replace('/USDT', ''))
            
            filters_config = {
                "core": True if scan_mode in ['all', 'core'] else False,
                "mtf": True if scan_mode in ['all', 'mtf'] else False,
                "vol": True if scan_mode in ['all', 'vol'] else False,
                "rsi": True if scan_mode in ['all', 'rsi'] else False
            }
            
            signal, price, details, atr_val = check_signal(coin, scan_tf, filters_config)
            
            if signal in ["BUY", "SELL"]:
                sl_dist = max(atr_val * ATR_MULTIPLIER, price * MIN_SL_PERCENTAGE)
                
                if signal == "BUY":
                    sl = price - sl_dist
                    tp1 = price + (sl_dist * 2) 
                    direction = "🟢 LONG"
                else:
                    sl = price + sl_dist
                    tp1 = price - (sl_dist * 2) 
                    direction = "🔴 SHORT"
                
                results.append({"coin": coin, "signal": direction, "price": price, "sl": sl, "tp1": tp1})
        
        proof_text = ", ".join(scanned_names)
        result_text = f"🔎 <b>SCAN COMPLETE ({scan_mode.upper()} on {scan_tf.upper()})</b>\n\n"
        result_text += f"<b>Coins Scanned ({len(scanned_names)}):</b>\n<i>{proof_text}</i>\n\n-----------------------------------\n\n"
        
        if not results:
            result_text += "❌ <b>Koi Signal Nahi Mila.</b>\nIn filters ke sath koi coin match nahi hua. WAIT karein."
            return result_text
            
        result_text += "🚀 <b>Signals Found:</b>\n\n"
        for res in results:
            result_text += f"<b>{res['coin']}</b> ({res['signal']})\n"
            result_text += f"💵 Entry: <code>{fmt(res['price'])}</code>\n"
            result_text += f"🛑 SL: <code>{fmt(res['sl'])}</code> | 🎯 TP1: <code>{fmt(res['tp1'])}</code>\n\n"
            
        return result_text
    except Exception as e:
        return f"❌ Market scan mein error aya: {e}"

# ==========================================
# 8. BUTTON HANDLER
# ==========================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_scanning, FILTER_CORE, FILTER_MTF, FILTER_VOLUME, FILTER_RSI, active_trades
    
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Access Denied.", show_alert=True)
        return
    await query.answer()
    
    if query.data == 'main_menu':
        text, reply_markup = get_main_menu()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    elif query.data == 'scan_menu':
        text, reply_markup = get_scan_menu()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    elif query.data.startswith('scan_tf_'):
        tf = query.data.replace('scan_tf_', '')
        keyboard = [
            [InlineKeyboardButton(f"🔥 ALL Filters ({tf})", callback_data=f'run_scan_all_{tf}')],
            [InlineKeyboardButton(f"📊 Core Only ({tf})", callback_data=f'run_scan_core_{tf}')],
            [InlineKeyboardButton("🔙 Back", callback_data='scan_menu')]
        ]
        await query.edit_message_text(f"🔎 <b>Scan Top 30 on {tf.upper()}</b>\nSelect Filters:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif query.data == 'sys_controls':
        keyboard = [
            [InlineKeyboardButton("🧹 Clear Active Trades", callback_data='clear_trades')],
            [InlineKeyboardButton("🔄 Refresh Memory", callback_data='reload_state')],
            [InlineKeyboardButton("🛑 Force Restart Bot", callback_data='force_restart')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
        ]
        await query.edit_message_text("🔄 <b>System Controls</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif query.data == 'clear_trades':
        active_trades.clear()
        save_state(active_trades)
        await query.edit_message_text("✅ <b>Active Trades Cleared!</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='sys_controls')]]), parse_mode='HTML')

    elif query.data == 'reload_state':
        active_trades = load_state()
        await query.edit_message_text(f"🔄 <b>Memory Refreshed!</b>\nLoaded {len(active_trades)} active trades.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='sys_controls')]]), parse_mode='HTML')

    elif query.data == 'force_restart':
        await query.edit_message_text("🛑 <b>Restarting Bot...</b>", parse_mode='HTML')
        await asyncio.sleep(2)
        os._exit(0)

    elif query.data.startswith('run_scan_'):
        if is_scanning:
            await query.answer("⏳ A scan is already in progress...", show_alert=True)
            return
        is_scanning = True
        parts = query.data.replace('run_scan_', '').split('_')
        scan_mode = parts[0] 
        scan_tf = parts[1] 

        await query.edit_message_text(f"⏳ <b>Scanning Top 30 ({scan_mode.upper()} on {scan_tf})...</b>", parse_mode='HTML')
        try:
            result_text = await asyncio.to_thread(run_market_scan, scan_mode, scan_tf)
            await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='scan_menu'), InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')]]), parse_mode='HTML')
        finally:
            is_scanning = False 

    elif query.data == 'active_trades':
        if not active_trades:
            await query.edit_message_text("📭 <b>No Active Trades.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')
            return
        
        text = "📈 <b>ACTIVE TRADES STATUS</b>\n\n"
        keyboard = []
        for trade_id, trade in active_trades.items():
            coin = trade_id.split('_')[0]
            tf = trade_id.split('_')[1]
            direction = trade['type']
            entry = trade['entry']
            sl = trade['sl']
            tp1 = trade['tp1']
            try:
                current_price = exchange.fetch_ticker(trade['coin'])['last']
            except Exception:
                current_price = entry
            status = "🟢 Profit" if (direction == "LONG" and current_price > entry) or (direction == "SHORT" and current_price < entry) else "🔴 Loss"
            text += f"<b>{coin} ({tf}) {direction}</b>\nEntry: <code>{fmt(entry)}</code> | Now: <code>{fmt(current_price)}</code>\nSL: <code>{fmt(sl)}</code> | TP1: <code>{fmt(tp1)}</code>\nStatus: {status}\n\n"
            keyboard.append([InlineKeyboardButton(f"❌ Cancel {coin}", callback_data=f"cancel_{trade_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='main_menu')])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif query.data.startswith('cancel_'):
        trade_id = query.data.replace('cancel_', '')
        if trade_id in active_trades:
            del active_trades[trade_id]
            save_state(active_trades)
        await query.edit_message_text(f"🗑️ Trade cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='active_trades')]]), parse_mode='HTML')

    elif query.data == 'market_summary':
        await query.edit_message_text("⏳ Fetching Basic Trend (9/21 EMA) for 30 coins...")
        summary_text = "🌐 <b>TOP 30 COINS BASIC TREND (1H)</b>\n\n"
        for coin in tracked_coins:
            trend = get_basic_trend(coin, '1h')
            emoji = "🟢" if trend == "BULLISH" else "🔴" if trend == "BEARISH" else "🟡"
            summary_text += f"<b>{coin}</b>: {emoji}\n"
        summary_text += "\n<i>Yeh sirf basic EMA 9/21 trend hai.</i>"
        await query.edit_message_text(summary_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data='market_summary'), InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

    elif query.data == 'analyze_coin':
        keyboard = [
            [InlineKeyboardButton("15m", callback_data='tf_15m'), InlineKeyboardButton("1h", callback_data='tf_1h')],
            [InlineKeyboardButton("4h", callback_data='tf_4h'), InlineKeyboardButton("1d", callback_data='tf_1d')],
            [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
        ]
        await query.edit_message_text("🔍 <b>Select Timeframe for Analysis:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif query.data.startswith('tf_'):
        selected_tf = query.data.replace('tf_', '')
        context.user_data['selected_tf'] = selected_tf
        context.user_data['awaiting_coin'] = True
        await query.edit_message_text(f"✅ Timeframe set to <b>{selected_tf}</b>.\n\nPlease send the coin name like this:\n<code>BTC/USDT</code>\n\nOr simply type: <code>BTC</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

    elif query.data == 'manage_coins':
        coins_list = "\n".join([f"• {coin}" for coin in tracked_coins])
        text = f"📊 <b>Tracked Coins ({len(tracked_coins)}):</b>\n{coins_list}\n\n<b>Add:</b> <code>/add DOGE</code>\n<b>Remove:</b> <code>/remove DOGE</code>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

    elif query.data == 'settings':
        keyboard = [
            [InlineKeyboardButton(f"Core Strategy: {'🟢 ON' if FILTER_CORE else '🔴 OFF'}", callback_data='toggle_core')],
            [InlineKeyboardButton(f"MTF Trend: {'🟢 ON' if FILTER_MTF else '🔴 OFF'}", callback_data='toggle_mtf')],
            [InlineKeyboardButton(f"Volume Filter: {'🟢 ON' if FILTER_VOLUME else '🔴 OFF'}", callback_data='toggle_vol')],
            [InlineKeyboardButton(f"RSI Filter: {'🟢 ON' if FILTER_RSI else '🔴 OFF'}", callback_data='toggle_rsi')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
        ]
        await query.edit_message_text("⚙️ <b>Terminal Settings</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data == 'toggle_core': FILTER_CORE = not FILTER_CORE; await button_handler(update, context) 
    elif query.data == 'toggle_mtf': FILTER_MTF = not FILTER_MTF; await button_handler(update, context)
    elif query.data == 'toggle_vol': FILTER_VOLUME = not FILTER_VOLUME; await button_handler(update, context)
    elif query.data == 'toggle_rsi': FILTER_RSI = not FILTER_RSI; await button_handler(update, context)

    elif query.data == 'help':
        help_text = "ℹ️ <b>Guide</b>\n\nYeh bot aapko timeframe select karne ki ijazat deta hai. Ab MTF logic 'Pairwise' hai:\n- 15m ke liye 1H check hoga\n- 1H ke liye 4H check hoga\n- 4H ke liye 1D check hoga.\n\n🛡️ ATR Floor: Minimum SL 1% set hai."
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

# ==========================================
# 9. MESSAGE HANDLER
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return

    if context.user_data.get('awaiting_coin'):
        context.user_data['awaiting_coin'] = False
        coin = update.message.text.strip().upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        
        selected_tf = context.user_data.get('selected_tf', '1h') 
            
        msg = await update.message.reply_text(f"🔍 Analyzing <b>{coin}</b> on <b>{selected_tf}</b>...", parse_mode='HTML')
        default_filters = {"core": True, "mtf": True, "vol": True, "rsi": True}
        
        signal, price, details, atr_val = check_signal(coin, selected_tf, default_filters)
        
        if signal == "ERROR":
            await msg.edit_text(f"❌ Error fetching data for <b>{coin}</b>.", parse_mode='HTML')
            return
            
        report = (f"<b>Analysis: {coin} ({selected_tf})</b>\n"
                  f"💵 Current Price: <code>{fmt(price)}</code>\n"
                  f"📊 Status: <b>{signal}</b>\n\n"
                  f"<b>Conditions Met:</b>\n{details}")
                  
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]), parse_mode='HTML')
    else:
        await update.message.reply_text("Please use the /start menu.")

# ==========================================
# 10. COMMANDS
# ==========================================
async def add_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin not in tracked_coins:
            tracked_coins.append(coin)
            await update.message.reply_text(f"✅ Added <b>{coin}</b>.", parse_mode='HTML')
        else:
            await update.message.reply_text(f"⚠️ {coin} already in list.")
    except:
        await update.message.reply_text("❌ Usage: /add DOGE")

async def remove_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin in tracked_coins:
            tracked_coins.remove(coin)
            await update.message.reply_text(f"🗑️ Removed <b>{coin}</b>.", parse_mode='HTML')
        else:
            await update.message.reply_text(f"⚠️ {coin} not found.")
    except:
        await update.message.reply_text("❌ Usage: /remove DOGE")

# ==========================================
# 11. SIGNAL ENGINES
# ==========================================
def get_basic_trend(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=30)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        ema9 = ta.trend.EMAIndicator(close=df['close'], window=9).ema_indicator().iloc[-1]
        ema21 = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator().iloc[-1]
        return "BULLISH" if ema9 > ema21 else "BEARISH"
    except:
        return "UNKNOWN"

def check_signal(symbol, timeframe, filters):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA9'] = ta.trend.EMAIndicator(close=df['close'], window=9).ema_indicator()
        df['EMA21'] = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['ADX'] = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14).adx()
        df['ROC'] = ta.momentum.ROCIndicator(close=df['close'], window=9).roc()
        df['RSI'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        df['Vol_SMA'] = df['volume'].rolling(window=20).mean()
        df['ATR'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
        
        c_close, c_open = df['close'].iloc[-1], df['open'].iloc[-1]
        c_low, c_high = df['low'].iloc[-1], df['high'].iloc[-1]
        
        c_ema9, c_ema21 = df['EMA9'].iloc[-1], df['EMA21'].iloc[-1]
        p_ema9, p_ema21 = df['EMA9'].iloc[-2], df['EMA21'].iloc[-2]
        c_adx, p_adx = df['ADX'].iloc[-1], df['ADX'].iloc[-2]
        c_roc, c_rsi = df['ROC'].iloc[-1], df['RSI'].iloc[-1]
        c_vol, c_vol_sma = df['volume'].iloc[-1], df['Vol_SMA'].iloc[-1]
        current_atr = df['ATR'].iloc[-1]
        
        signal = "WAIT"
        details = ""
        
        candle_range = c_high - c_low
        if candle_range == 0: return "WAIT", c_close, "❌ No Movement.", current_atr
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low
        if upper_wick > (candle_range * 0.5) or lower_wick > (candle_range * 0.5):
            return "WAIT", c_close, "❌ Rejected: Whale Wick (Manipulation).", current_atr

        if filters.get("core"):
            bullish_cross = (p_ema9 <= p_ema21) and (c_ema9 > c_ema21)
            bearish_cross = (p_ema9 >= p_ema21) and (c_ema9 < c_ema21)
            bullish_pullback = (c_low <= c_ema9) and (c_close > c_ema9)
            bearish_pullback = (c_high >= c_ema9) and (c_close < c_ema9)
            adx_rising = c_adx > p_adx and c_adx > 20

            if (bullish_cross or bullish_pullback) and c_ema9 > c_ema21 and adx_rising and c_roc > 0:
                signal = "BUY"
                details += f"✅ Core: Bullish Pullback + ADX Rising\n"
            elif (bearish_cross or bearish_pullback) and c_ema9 < c_ema21 and adx_rising and c_roc < 0:
                signal = "SELL"
                details += f"✅ Core: Bearish Pullback + ADX Rising\n"
            else:
                return "WAIT", c_close, "❌ Core Strategy not met.", current_atr
        else:
            if c_ema9 > c_ema21: signal = "BUY"
            elif c_ema9 < c_ema21: signal = "SELL"
            
        if filters.get("mtf"):
            higher_tf = None
            if timeframe == '15m': higher_tf = '1h'
            elif timeframe == '1h': higher_tf = '4h'
            elif timeframe == '4h': higher_tf = '1d'
            
            if higher_tf:
                htf_trend = get_basic_trend(symbol, higher_tf)
                if (signal == "BUY" and htf_trend == "BULLISH") or (signal == "SELL" and htf_trend == "BEARISH"):
                    details += f"✅ MTF Aligned ({higher_tf} is {htf_trend})\n"
                else:
                    return "WAIT", c_close, details + f"❌ Rejected: {higher_tf} is {htf_trend} (Conflict).", current_atr

        if filters.get("vol"):
            if c_vol > (c_vol_sma * 1.2):
                details += f"✅ Volume Confirmed\n"
            else:
                return "WAIT", c_close, details + f"❌ Low Volume.", current_atr

        if filters.get("rsi"):
            if signal == "BUY" and 40 < c_rsi < 70:
                details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            elif signal == "SELL" and 30 < c_rsi < 60:
                details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            else:
                return "WAIT", c_close, details + f"❌ RSI Extreme.", current_atr

        return signal, c_close, details, current_atr
    except Exception as e:
        return "ERROR", 0, "", 0

# ==========================================
# 12. BACKGROUND SCANNER & TRADE MANAGER
# ==========================================
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    global active_trades
    bg_filters = {"core": FILTER_CORE, "mtf": FILTER_MTF, "vol": FILTER_VOLUME, "rsi": FILTER_RSI}
    
    if not is_trading_session(): return 
    
    # Limit hata di gayi hai. Ab bot jitne bhi signals banenge sab track karega.
    
    for coin in tracked_coins:
        for tf in timeframes: 
            signal, price, details, atr_val = check_signal(coin, tf, bg_filters)
            if signal in ["BUY", "SELL"]:
                trade_id = f"{coin}_{tf}_{signal}"
                if trade_id not in active_trades:
                    
                    sl_dist = max(atr_val * ATR_MULTIPLIER, price * MIN_SL_PERCENTAGE)
                    
                    if signal == "BUY":
                        sl = price - sl_dist
                        tp1 = price + (sl_dist * 2) 
                        tp2 = price + (sl_dist * 4) 
                        emoji, direction = "🟢", "LONG"
                    else:
                        sl = price + sl_dist
                        tp1 = price - (sl_dist * 2) 
                        tp2 = price - (sl_dist * 4) 
                        emoji, direction = "🔴", "SHORT"
                    
                    active_trades[trade_id] = {"coin": coin, "entry": price, "sl": sl, "tp1": tp1, "tp2": tp2, "type": direction, "tp1_hit": False, "sl_moved": False}
                    save_state(active_trades)
                    
                    msg = (f"{emoji} <b>{direction}: {coin}</b> ({tf})\n\n"
                           f"💵 Entry: <code>{fmt(price)}</code>\n"
                           f"🛑 SL: <code>{fmt(sl)}</code> (ATR Floor: 1%)\n"
                           f"🎯 TP1 (50%): <code>{fmt(tp1)}</code>\n"
                           f"🎯 TP2 (50%): <code>{fmt(tp2)}</code>\n\n"
                           f"<b>Details:</b>\n{details}")
                    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')

    for trade_id, trade in list(active_trades.items()):
        try:
            current_price = exchange.fetch_ticker(trade['coin'])['last']
        except Exception:
            continue

        entry, sl, tp1, tp2, direction = trade['entry'], trade['sl'], trade['tp1'], trade['tp2'], trade['type']
        if not trade['tp1_hit']:
            if (direction == "LONG" and current_price >= tp1) or (direction == "SHORT" and current_price <= tp1):
                trade['tp1_hit'] = True
                trade['sl'] = entry
                trade['sl_moved'] = True
                save_state(active_trades)
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"🎯 <b>TP1 HIT: {trade['coin']}</b>\n✅ 50% Booked. SL moved to Breakeven (<code>{fmt(entry)}</code>).", parse_mode='HTML')
        
        if (direction == "LONG" and current_price >= tp2) or (direction == "SHORT" and current_price <= tp2):
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🏆 <b>TP2 HIT: {trade['coin']}</b>\n✅ Full Trade Closed.", parse_mode='HTML')
            del active_trades[trade_id]
            save_state(active_trades)
            continue

        if (direction == "LONG" and current_price <= sl) or (direction == "SHORT" and current_price >= sl):
            status = "Breakeven" if trade['sl_moved'] else "Loss (ATR SL)"
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔴 <b>SL HIT: {trade['coin']}</b>\n❌ Closed at {status}.", parse_mode='HTML')
            del active_trades[trade_id]
            save_state(active_trades)

# ==========================================
# 13. HEARTBEAT SYSTEM
# ==========================================
async def heartbeat_status(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now().strftime("%I:%M %p")
    is_active = is_trading_session()
    status_text = "🟢 SCANNING" if is_active else "💤 SLEEPING (Out of Session)"
    
    active_count = len(active_trades)
    scanned_msg = f"✅ <b>Heartbeat Status ({now})</b>\n\n"
    scanned_msg += f"🤖 Bot Status: {status_text}\n"
    scanned_msg += f"📊 Tracking {len(tracked_coins)} coins.\n"
    scanned_msg += f"📈 Total Signals Tracked: {active_count}\n\n"
    
    if is_active and active_count == 0:
        scanned_msg += "<i>Abhi tak koi strong signal nahi mila. Market scan jari hai...</i>"
    elif not is_active:
        scanned_msg += "<i>Abhi market session active nahi hai. Bot rest kar raha hai.</i>"
    
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=scanned_msg, parse_mode='HTML')
    except Exception:
        pass

# ==========================================
# 14. MAIN
# ==========================================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("add", add_coin_cmd))
    app_bot.add_handler(CommandHandler("remove", remove_coin_cmd))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_bot.add_error_handler(error_handler)
    
    job_queue = app_bot.job_queue
    job_queue.run_repeating(scan_market, interval=600, first=10)
    job_queue.run_repeating(heartbeat_status, interval=10800, first=60)

    print("Ultimate Pro Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
