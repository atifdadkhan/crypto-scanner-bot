import os
import json
import ccxt
import pandas as pd
import pandas_ta as ta
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==========================================
# 1. CONFIGURATION (Token & Chat ID)
# ==========================================
TELEGRAM_TOKEN = "8664137345:AAF7ROx4_6PSTHYPKop-Ytf73CQB2Ekw_2g"
YOUR_CHAT_ID = 6620183989 

LEVERAGE = 10 
STATE_FILE = "trades.json"
exchange = ccxt.binance() 
tracked_coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT']
timeframes = ['15m', '1h', '4h', '1d']

# ==========================================
# 2. FLASK WEB SERVER (Render ke liye zaroori)
# ==========================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running", 200

def run_flask():
    # Render PORT environment variable deta hai
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
# 4. TELEGRAM COMMANDS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 **Crypto Scanner Bot Active!**\n\n"
                                    "Main aapko Spot aur Futures ke signals bhejunga.\n"
                                    "/list, /add, /remove, /status")

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
    await update.message.reply_text(f"📡 **Status**\nActive Trades: {len(active_trades)}\nSource: Binance\nStatus: Running")

# ==========================================
# 5. SIGNAL ENGINE (EMA + ADX + ROC)
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
        
        if ema_cross_up and current_adx > 25 and current_roc > 0:
            return "BUY", current_close
        elif ema_cross_down and current_adx > 25 and current_roc < 0:
            return "SELL", current_close
        else:
            return "WAIT", current_close
    except Exception as e:
        print(f"Error on {symbol}: {e}")
        return "ERROR", 0

# ==========================================
# 6. BACKGROUND SCANNER
# ==========================================
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    global active_trades
    
    for coin in tracked_coins:
        for tf in timeframes:
            status, price = check_signal(coin, tf)
            spot_id = f"{coin}_{tf}_SPOT"
            
            # Spot BUY
            if status == "BUY" and spot_id not in active_trades:
                active_trades[spot_id] = {"entry": price, "hit3": False, "hit5": False, "hit7": False}
                save_state(active_trades)
                msg = (f"🟢 **SPOT BUY: {coin}**\n⏱ {tf}\n💵 {price}\n🎯 3% | 5% | 7%")
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')
            
            if status == "SELL" and spot_id in active_trades:
                del active_trades[spot_id]
                save_state(active_trades)
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"⚠️ **SPOT EXIT: {coin}**\n⏱ {tf}\n💵 {price}")

            # Spot Profit
            if spot_id in active_trades:
                entry = active_trades[spot_id]["entry"]
                pct = ((price - entry) / entry) * 100
                for target, key in [(3, "hit3"), (5, "hit5"), (7, "hit7")]:
                    if pct >= target and not active_trades[spot_id][key]:
                        active_trades[spot_id][key] = True
                        save_state(active_trades)
                        await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"🎯 **SPOT PROFIT: {coin} (+{target}%)**\nPrice: {price}")

            # Futures
            fut_id = f"{coin}_{tf}_FUT"
            if status == "BUY" and fut_id not in active_trades:
                active_trades[fut_id] = {"entry": price, "type": "LONG", "hit20": False, "hit30": False, "hit50": False}
                save_state(active_trades)
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"🚀 **FUTURES LONG: {coin}**\n⏱ {tf}\n💵 {price}\n⚠️ Est. ROI (10x): 20% | 30% | 50%")
            
            if status == "SELL" and f"{fut_id}_SHORT" not in active_trades:
                active_trades[f"{fut_id}_SHORT"] = {"entry": price, "type": "SHORT", "hit20": False, "hit30": False, "hit50": False}
                save_state(active_trades)
                await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"🔴 **FUTURES SHORT: {coin}**\n⏱ {tf}\n💵 {price}\n⚠️ Est. ROI (10x): 20% | 30% | 50%")

            if fut_id in active_trades:
                entry = active_trades[fut_id]["entry"]
                roi = ((price - entry) / entry) * 100 * LEVERAGE
                for target, key in [(20, "hit20"), (30, "hit30"), (50, "hit50")]:
                    if roi >= target and not active_trades[fut_id][key]:
                        active_trades[fut_id][key] = True
                        save_state(active_trades)
                        await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES LONG: {coin} (+{target}% ROI)**\nPrice: {price}")
            
            if f"{fut_id}_SHORT" in active_trades:
                entry = active_trades[f"{fut_id}_SHORT"]["entry"]
                roi = ((entry - price) / entry) * 100 * LEVERAGE
                for target, key in [(20, "hit20"), (30, "hit30"), (50, "hit50")]:
                    if roi >= target and not active_trades[f"{fut_id}_SHORT"][key]:
                        active_trades[f"{fut_id}_SHORT"][key] = True
                        save_state(active_trades)
                        await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=f"💰 **FUTURES SHORT: {coin} (+{target}% ROI)**\nPrice: {price}")

# ==========================================
# 7. MAIN
# ==========================================
def main():
    # Flask ko alag thread mein chalayein taake Render ka port block na ho
    threading.Thread(target=run_flask, daemon=True).start()
    
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("list", list_coins))
    app_bot.add_handler(CommandHandler("add", add_coin))
    app_bot.add_handler(CommandHandler("remove", remove_coin))
    app_bot.add_handler(CommandHandler("status", status))
    
    job_queue = app_bot.job_queue
    job_queue.run_repeating(scan_market, interval=600, first=10)

    print("Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
