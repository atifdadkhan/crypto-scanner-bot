import os
import json
import ccxt
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==========================================
# 1. CONFIGURATION (Token & Chat ID)
# ==========================================
# Aapka Bot Token (Isko BotFather se naya revoke kar ke badal lein)
TELEGRAM_TOKEN = "8664137345:AAF7ROx4_6PSTHYPKop-Ytf73CQB2Ekw_2g"
# Aapki Asli Chat ID
YOUR_CHAT_ID = 6620183989 

LEVERAGE = 10 # Futures ROI calculation ke liye
STATE_FILE = "trades.json"

# Public Data Source (No Login/API Key Required)
exchange = ccxt.binance() 

# Default Coins
tracked_coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']
timeframes = ['15m', '1h', '4h', '1d']

# ==========================================
# 2. STATE MANAGEMENT (Local JSON File)
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
# 3. TELEGRAM COMMANDS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 **Crypto Scanner Bot Active!**\n\n"
                                    "Main aapko Spot aur Futures ke signals bhejunga.\n"
                                    "Commands:\n"
                                    "/list - Tracked coins\n"
                                    "/add BTC/USDT - Add coin\n"
                                    "/remove BTC/USDT - Remove coin\n"
                                    "/status - Last scan status")

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Tracking: {', '.join(tracked_coins)}")

async def add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin not in tracked_coins:
            tracked_coins.append(coin)
            await update.message.reply_text(f"✅ Added {coin}")
        else:
            await update.message.reply_text(f"⚠️ {coin} already in list.")
    except:
        await update.message.reply_text("❌ Usage: /add BTC/USDT")

async def remove_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin in tracked_coins:
            tracked_coins.remove(coin)
            await update.message.reply_text(f"🗑️ Removed {coin}")
        else:
            await update.message.reply_text(f"⚠️ {coin} not in list.")
    except:
        await update.message.reply_text("❌ Usage: /remove BTC/USDT")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📡 **Status**\n"
                                    f"Active Trades Tracked: {len(active_trades)}\n"
                                    f"Data Source: Binance Public API\n"
                                    f"Last Scan: Just Now")

# ==========================================
# 4. SIGNAL ENGINE (EMA + ADX + ROC)
# ==========================================
def check_signal(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        
        df['EMA9'] = ta.ema(df['close'], length=9)
        df['EMA21'] = ta.ema(df['close'], length=21)
        df['ADX'] = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14']
        df['ROC'] = ta.roc(df['close'], length=9)
        
        current_close = df['close'].iloc[-1]
        current_ema9 = df['EMA9'].iloc[-1]
        current_ema21 = df['EMA21'].iloc[-1]
        prev_ema9 = df['EMA9'].iloc[-2]
        prev_ema21 = df['EMA21'].iloc[-2]
        current_adx = df['ADX'].iloc[-1]
        current_roc = df['ROC'].iloc[-1]
        
        ema_cross_up = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
        ema_cross_down = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
        is_adx_strong = current_adx > 25
        is_roc_positive = current_roc > 0
        is_roc_negative = current_roc < 0
        
        if ema_cross_up and is_adx_strong and is_roc_positive:
            return "BUY", current_close
        elif ema_cross_down and is_adx_strong and is_roc_negative:
            return "SELL", current_close
        else:
            return "WAIT", current_close
    except Exception as e:
        print(f"Error on {symbol}: {e}")
        return "ERROR", 0

# ==========================================
# 5. BACKGROUND SCANNER & ALERTS
# ==========================================
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    global active_trades
    
    for coin in tracked_coins:
        for tf in timeframes:
            
            # --- SPOT MARKET ---
            status, price = check_signal(coin, tf)
            spot_id = f"{coin}_{tf}_SPOT"
            
            if status == "BUY" and spot_id not in active_trades:
                active_trades[spot_id] = {"entry": price, "hit3": False, "hit5": False, "hit7": False}
                save_state(active_trades)
                msg = (f"🟢 **SPOT BUY: {coin}**\n"
                       f"⏱ Timeframe: {tf}\n"
                       f"💵 Entry: {price}\n"
                       f"🎯 Targets: 3% | 5% | 7%")
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')
            
            if status == "SELL":
                if spot_id in active_trades:
                    del active_trades[spot_id]
                    save_state(active_trades)
                msg = (f"⚠️ **SPOT EXIT: {coin}**\n"
                       f"⏱ Timeframe: {tf}\n"
                       f"💵 Price: {price}\n"
                       f"🔴 Trend changing. Consider selling.")
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')

            # Spot Profit Booking
            if spot_id in active_trades:
                entry = active_trades[spot_id]["entry"]
                current_pct = ((price - entry) / entry) * 100
                
                if current_pct >= 3 and not active_trades[spot_id]["hit3"]:
                    active_trades[spot_id]["hit3"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"🎯 **SPOT PROFIT: {coin} (+3%)**\nPrice: {price}")
                if current_pct >= 5 and not active_trades[spot_id]["hit5"]:
                    active_trades[spot_id]["hit5"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"🎯 **SPOT PROFIT: {coin} (+5%)**\nPrice: {price}")
                if current_pct >= 7 and not active_trades[spot_id]["hit7"]:
                    active_trades[spot_id]["hit7"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"🎯 **SPOT PROFIT: {coin} (+7%)**\nPrice: {price}")

            # --- FUTURES MARKET (Estimated ROI) ---
            fut_id = f"{coin}_{tf}_FUT"
            if status == "BUY" and fut_id not in active_trades:
                active_trades[fut_id] = {"entry": price, "type": "LONG", "hit20": False, "hit30": False, "hit50": False}
                save_state(active_trades)
                msg = (f"🚀 **FUTURES LONG: {coin}**\n"
                       f"⏱ Timeframe: {tf}\n"
                       f"💵 Entry: {price}\n"
                       f"⚠️ *Estimated ROI (10x): 20% | 30% | 50%*")
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')
            
            if status == "SELL" and f"{fut_id}_SHORT" not in active_trades:
                active_trades[f"{fut_id}_SHORT"] = {"entry": price, "type": "SHORT", "hit20": False, "hit30": False, "hit50": False}
                save_state(active_trades)
                msg = (f"🔴 **FUTURES SHORT: {coin}**\n"
                       f"⏱ Timeframe: {tf}\n"
                       f"💵 Entry: {price}\n"
                       f"⚠️ *Estimated ROI (10x): 20% | 30% | 50%*")
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')

            # Futures Profit Booking
            if fut_id in active_trades and active_trades[fut_id]["type"] == "LONG":
                entry = active_trades[fut_id]["entry"]
                roi = ((price - entry) / entry) * 100 * LEVERAGE
                
                if roi >= 20 and not active_trades[fut_id]["hit20"]:
                    active_trades[fut_id]["hit20"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES LONG: {coin} (+20% Est. ROI)**\nPrice: {price}")
                if roi >= 30 and not active_trades[fut_id]["hit30"]:
                    active_trades[fut_id]["hit30"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES LONG: {coin} (+30% Est. ROI)**\nPrice: {price}")
                if roi >= 50 and not active_trades[fut_id]["hit50"]:
                    active_trades[fut_id]["hit50"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES LONG: {coin} (+50% Est. ROI)**\nPrice: {price}")

            if f"{fut_id}_SHORT" in active_trades and active_trades[f"{fut_id}_SHORT"]["type"] == "SHORT":
                entry = active_trades[f"{fut_id}_SHORT"]["entry"]
                roi = ((entry - price) / entry) * 100 * LEVERAGE
                
                if roi >= 20 and not active_trades[f"{fut_id}_SHORT"]["hit20"]:
                    active_trades[f"{fut_id}_SHORT"]["hit20"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES SHORT: {coin} (+20% Est. ROI)**\nPrice: {price}")
                if roi >= 30 and not active_trades[f"{fut_id}_SHORT"]["hit30"]:
                    active_trades[f"{fut_id}_SHORT"]["hit30"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES SHORT: {coin} (+30% Est. ROI)**\nPrice: {price}")
                if roi >= 50 and not active_trades[f"{fut_id}_SHORT"]["hit50"]:
                    active_trades[f"{fut_id}_SHORT"]["hit50"] = True
                    save_state(active_trades)
                    await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES SHORT: {coin} (+50% Est. ROI)**\nPrice: {price}")

# ==========================================
# 6. MAIN FUNCTION
# ==========================================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_coins))
    app.add_handler(CommandHandler("add", add_coin))
    app.add_handler(CommandHandler("remove", remove_coin))
    app.add_handler(CommandHandler("status", status))
    
    job_queue = app.job_queue
    job_queue.run_repeating(scan_market, interval=600, first=10)

    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
