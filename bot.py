import os
import json
import ccxt
import pandas as pd
import ta
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ==========================================
# 1. CONFIGURATION (Your Personal Bot)
# ==========================================
TELEGRAM_TOKEN = "8664137345:AAF7ROx4_6PSTHYPKop-Ytf73CQB2Ekw_2g" 
ADMIN_ID = 6620183989  # YOUR CHAT ID (Bot is locked to this ID)

LEVERAGE = 10 
STATE_FILE = "trades.json"
exchange = ccxt.bitget() 

# Top 15 Strong Coins (Default)
tracked_coins = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'MATIC/USDT',
    'NEAR/USDT', 'INJ/USDT', 'SUI/USDT', 'OP/USDT', 'ARB/USDT'
]
timeframes = ['15m', '1h', '4h', '1d']

# Filters (Default ON)
FILTER_CORE = True
FILTER_MTF = True
FILTER_VOLUME = True
FILTER_RSI = True

# ==========================================
# 2. FLASK WEB SERVER (Render Keep-Alive)
# ==========================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 3. STATE MANAGEMENT
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

active_trades = load_state()

# ==========================================
# 4. TELEGRAM UI & SECURITY
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 🔒 SECURITY LOCK
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ <b>Access Denied.</b>\nThis is a private trading bot.", parse_mode='HTML')
        return

    keyboard = [
        [InlineKeyboardButton("⚙️ Filters & Settings", callback_data='settings')],
        [InlineKeyboardButton("📊 Manage Coins", callback_data='manage_coins')],
        [InlineKeyboardButton("📈 Bot Status", callback_data='status')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "🤖 <b>Welcome to Your Personal Trading Assistant!</b>\n\n"
        "Main background mein Top 15 coins ko scan karta rahunga aur strong signals par aapko alert dunga.\n\n"
        "🔍 <b>Manual Check:</b>\n"
        "Type karein: <code>/check BTC/USDT</code> (Kisi bhi coin ka live analysis)\n\n"
        "Neeche diye gaye buttons se settings manage karein:"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id != ADMIN_ID:
        await query.answer("⛔ Access Denied.", show_alert=True)
        return
        
    await query.answer()
    global FILTER_CORE, FILTER_MTF, FILTER_VOLUME, FILTER_RSI
    
    if query.data == 'settings':
        keyboard = [
            [InlineKeyboardButton(f"Core Strategy: {'🟢 ON' if FILTER_CORE else '🔴 OFF'}", callback_data='toggle_core')],
            [InlineKeyboardButton(f"MTF Trend Filter: {'🟢 ON' if FILTER_MTF else '🔴 OFF'}", callback_data='toggle_mtf')],
            [InlineKeyboardButton(f"Volume Spike: {'🟢 ON' if FILTER_VOLUME else '🔴 OFF'}", callback_data='toggle_vol')],
            [InlineKeyboardButton(f"RSI Safe Zone: {'🟢 ON' if FILTER_RSI else '🔴 OFF'}", callback_data='toggle_rsi')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
        ]
        await query.edit_message_text("⚙️ <b>Bot Settings</b>\n\nFilters ON/OFF karne ke liye click karein. Background scanner inhi settings par chalega.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data == 'toggle_core':
        FILTER_CORE = not FILTER_CORE
        await button_handler(update, context) 
    elif query.data == 'toggle_mtf':
        FILTER_MTF = not FILTER_MTF
        await button_handler(update, context)
    elif query.data == 'toggle_vol':
        FILTER_VOLUME = not FILTER_VOLUME
        await button_handler(update, context)
    elif query.data == 'toggle_rsi':
        FILTER_RSI = not FILTER_RSI
        await button_handler(update, context)
        
    elif query.data == 'main_menu':
        await start(update, context)
        
    elif query.data == 'manage_coins':
        coins_list = "\n".join([f"• {coin}" for coin in tracked_coins])
        help_text = (
            f"📊 <b>Tracked Coins ({len(tracked_coins)}):</b>\n{coins_list}\n\n"
            f"<b>To Add a Coin:</b>\n<code>/add DOGE/USDT</code>\n\n"
            f"<b>To Remove a Coin:</b>\n<code>/remove DOGE/USDT</code>"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
    elif query.data == 'status':
        status_text = (
            f"📡 <b>Bot Status</b>\n\n"
            f"🟢 Running\n"
            f"Active Trades Tracked: {len(active_trades)}\n"
            f"Source: Bitget\n"
            f"Coins Scanned: {len(tracked_coins)}\n"
            f"Timeframes: {', '.join(timeframes)}"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        await query.edit_message_text(status_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif query.data == 'help':
        help_text = (
            "ℹ️ <b>How to use this bot?</b>\n\n"
            "1️⃣ <b>On-Demand Check:</b> Kisi bhi coin ka analysis karne ke liye likhein <code>/check COIN/USDT</code>.\n\n"
            "2️⃣ <b>Background Alerts:</b> Bot khud se Top 15 coins ko check karega. Jab bhi koi strong signal banega, aapko message aayega.\n\n"
            "3️⃣ <b>Manage Filters:</b> Aap settings mein ja kar kisi bhi filter ko ON/OFF kar sakte hain.\n\n"
            "4️⃣ <b>Coin Management:</b> <code>/add COIN</code> ya <code>/remove COIN</code> se list update karein.\n\n"
            "5️⃣ <b>Risk Warning:</b> Hamesha diye gaye Stop Loss (SL) ka istemal karein."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# ==========================================
# 5. COMMANDS (/check, /add, /remove)
# ==========================================
async def check_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
    except:
        await update.message.reply_text("❌ Usage: /check BTC/USDT")
        return
    
    msg = await update.message.reply_text(f"🔍 Analyzing {coin}... Please wait.")
    
    # Check on 1h timeframe by default
    signal, price, strength, details = check_signal(coin, '1h')
    
    if signal == "ERROR":
        await msg.edit_text(f"❌ Error fetching data for {coin}. Make sure it's available on Bitget.")
        return
        
    if signal == "WAIT":
        report = (f"⏳ <b>Analysis: {coin} (1H)</b>\n\n"
                  f"💵 Price: {price}\n"
                  f"📊 Status: <b>WAIT (No Clear Signal)</b>\n\n"
                  f"<b>Condition Breakdown:</b>\n{details}")
    elif signal == "BUY":
        report = (f"🟢 <b>Analysis: {coin} (1H)</b>\n\n"
                  f"💵 Price: {price}\n"
                  f"⭐ Strength: {strength}%\n"
                  f"📊 Status: <b>BUY SIGNAL</b>\n\n"
                  f"<b>Conditions Met:</b>\n{details}")
    elif signal == "SELL":
        report = (f"🔴 <b>Analysis: {coin} (1H)</b>\n\n"
                  f"💵 Price: {price}\n"
                  f"⭐ Strength: {strength}%\n"
                  f"📊 Status: <b>SELL SIGNAL</b>\n\n"
                  f"<b>Conditions Met:</b>\n{details}")
                  
    await msg.edit_text(report, parse_mode='HTML')

async def add_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin not in tracked_coins:
            tracked_coins.append(coin)
            await update.message.reply_text(f"✅ Added {coin} to background scanner.")
        else:
            await update.message.reply_text(f"⚠️ {coin} is already in list.")
    except:
        await update.message.reply_text("❌ Usage: /add DOGE/USDT")

async def remove_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin in tracked_coins:
            tracked_coins.remove(coin)
            await update.message.reply_text(f"🗑️ Removed {coin} from scanner.")
        else:
            await update.message.reply_text(f"⚠️ {coin} not found.")
    except:
        await update.message.reply_text("❌ Usage: /remove DOGE/USDT")

# ==========================================
# 6. SIGNAL ENGINE (Detailed Analysis Logic)
# ==========================================
def check_mtf_trend(symbol, current_tf):
    try:
        check_tf = '4h' if current_tf in ['15m', '1h'] else '1d'
        ohlcv = exchange.fetch_ohlcv(symbol, check_tf, limit=30)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        ema9 = ta.trend.EMAIndicator(close=df['close'], window=9).ema_indicator().iloc[-1]
        ema21 = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator().iloc[-1]
        return "BULLISH" if ema9 > ema21 else "BEARISH"
    except:
        return "UNKNOWN"

def check_signal(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA9'] = ta.trend.EMAIndicator(close=df['close'], window=9).ema_indicator()
        df['EMA21'] = ta.trend.EMAIndicator(close=df['close'], window=21).ema_indicator()
        df['ADX'] = ta.trend.ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14).adx()
        df['ROC'] = ta.momentum.ROCIndicator(close=df['close'], window=9).roc()
        df['RSI'] = ta.momentum.RSIIndicator(close=df['close'], window=14).rsi()
        df['Vol_SMA'] = df['volume'].rolling(window=20).mean()
        
        c_close = df['close'].iloc[-1]
        c_ema9 = df['EMA9'].iloc[-1]
        c_ema21 = df['EMA21'].iloc[-1]
        p_ema9 = df['EMA9'].iloc[-2]
        p_ema21 = df['EMA21'].iloc[-2]
        c_adx = df['ADX'].iloc[-1]
        c_roc = df['ROC'].iloc[-1]
        c_rsi = df['RSI'].iloc[-1]
        c_vol = df['volume'].iloc[-1]
        c_vol_sma = df['Vol_SMA'].iloc[-1]
        
        ema_cross_up = (p_ema9 <= p_ema21) and (c_ema9 > c_ema21)
        ema_cross_down = (p_ema9 >= p_ema21) and (c_ema9 < c_ema21)
        
        # Check if Core Filter is ON
        if not FILTER_CORE:
            return "WAIT", c_close, 0, "❌ Core Strategy is turned OFF in settings."

        if ema_cross_up and c_adx > 25 and c_roc > 0:
            signal = "BUY"
        elif ema_cross_down and c_adx > 25 and c_roc < 0:
            signal = "SELL"
        else:
            return "WAIT", c_close, 0, "❌ Core Strategy not met (Needs EMA Cross, ADX > 25, ROC direction)."
            
        strength = 60 
        details = ""
        details += f"✅ Core: EMA Cross, ADX({c_adx:.1f}), ROC({c_roc:.1f})\n"
        
        # Filter 1: MTF
        if FILTER_MTF:
            mtf_trend = check_mtf_trend(symbol, timeframe)
            if (signal == "BUY" and mtf_trend == "BULLISH") or (signal == "SELL" and mtf_trend == "BEARISH"):
                strength += 15
                details += f"✅ MTF Aligned (Higher TF is {mtf_trend})\n"
            else:
                return "WAIT", c_close, 0, details + f"❌ Rejected: MTF Conflict (Higher TF is {mtf_trend})."
                
        # Filter 2: Volume
        if FILTER_VOLUME:
            if c_vol > (c_vol_sma * 1.5):
                strength += 15
                details += f"✅ Volume Spike ({c_vol/c_vol_sma:.1f}x)\n"
            else:
                return "WAIT", c_close, 0, details + f"❌ Rejected: Low Volume ({c_vol/c_vol_sma:.1f}x)."
                
        # Filter 3: RSI
        if FILTER_RSI:
            if signal == "BUY" and 45 < c_rsi < 70:
                strength += 10
                details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            elif signal == "SELL" and 30 < c_rsi < 55:
                strength += 10
                details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            else:
                return "WAIT", c_close, 0, details + f"❌ Rejected: RSI Extreme ({c_rsi:.1f})."

        return signal, c_close, strength, details
        
    except Exception as e:
        print(f"Error on {symbol}: {e}")
        return "ERROR", 0, 0, ""

# ==========================================
# 7. BACKGROUND SCANNER (Top 15 Coins)
# ==========================================
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    global active_trades
    
    for coin in tracked_coins:
        for tf in timeframes:
            signal, price, strength, details = check_signal(coin, tf)
            
            if signal == "WAIT" or signal == "ERROR":
                continue
                
            # --- SPOT LOGIC ---
            if signal == "BUY":
                spot_id = f"{coin}_{tf}_SPOT"
                if spot_id not in active_trades:
                    active_trades[spot_id] = {"entry": price}
                    save_state(active_trades)
                    msg = (f"🟢 <b>SPOT BUY: {coin}</b> ({tf})\n"
                           f"⭐ <b>Strength: {strength}%</b>\n\n"
                           f"💵 Entry: {price}\n"
                           f"🎯 Target: {price * 1.05:.4f} (+5%)\n"
                           f"🛑 SL: {price * 0.98:.4f} (-2%)\n\n"
                           f"<b>Filters Passed:</b>\n{details}")
                    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')

            # --- FUTURES LOGIC ---
            fut_id = f"{coin}_{tf}_FUT"
            if signal == "BUY":
                if fut_id not in active_trades:
                    active_trades[fut_id] = {"entry": price, "type": "LONG"}
                    save_state(active_trades)
                    msg = (f"🚀 <b>FUTURES LONG: {coin}</b> ({tf})\n"
                           f"⭐ <b>Strength: {strength}%</b>\n\n"
                           f"💵 Entry: {price}\n"
                           f"🎯 Target (20% ROI): {price * 1.02:.4f}\n"
                           f"🛑 SL (-20% ROI): {price * 0.98:.4f}\n\n"
                           f"<b>Filters Passed:</b>\n{details}")
                    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')
                    
            elif signal == "SELL":
                if f"{fut_id}_SHORT" not in active_trades:
                    active_trades[f"{fut_id}_SHORT"] = {"entry": price, "type": "SHORT"}
                    save_state(active_trades)
                    msg = (f"🔴 <b>FUTURES SHORT: {coin}</b> ({tf})\n"
                           f"⭐ <b>Strength: {strength}%</b>\n\n"
                           f"💵 Entry: {price}\n"
                           f"🎯 Target (20% ROI): {price * 0.98:.4f}\n"
                           f"🛑 SL (-20% ROI): {price * 1.02:.4f}\n\n"
                           f"<b>Filters Passed:</b>\n{details}")
                    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')

# ==========================================
# 8. MAIN
# ==========================================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("check", check_coin_cmd))
    app_bot.add_handler(CommandHandler("add", add_coin_cmd))
    app_bot.add_handler(CommandHandler("remove", remove_coin_cmd))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    
    job_queue = app_bot.job_queue
    job_queue.run_repeating(scan_market, interval=600, first=10)

    print("Personal Pro Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
