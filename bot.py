import os
import json
import ccxt
import pandas as pd
import ta
import threading
import asyncio
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# ==========================================
# 1. CONFIGURATION
# ==========================================
TELEGRAM_TOKEN = "8664137345:AAF7ROx4_6PSTHYPKop-Ytf73CQB2Ekw_2g" 
YOUR_CHAT_ID = 6620183989 

LEVERAGE = 10 
STATE_FILE = "trades.json"

exchange = ccxt.bitget() 

timeframes = ['15m', '1h', '4h', '1d']

# Toggles (Filter Settings)
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
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"State save error: {e}")

active_trades = load_state()

# ==========================================
# 4. TELEGRAM UI & COMMANDS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [
            [InlineKeyboardButton("⚙️ Settings (Filters)", callback_data='settings')],
            [InlineKeyboardButton("📊 Tracked Coins (Top 10 Vol)", callback_data='list_coins')],
            [InlineKeyboardButton("📈 Bot Status", callback_data='status')],
            [InlineKeyboardButton("🗑️ Clear Active Trades", callback_data='clear_trades')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg_text = ("🤖 **Welcome to Professional Crypto Scanner!**\n\n"
                    "Main Bitget ke data par high-probability signals dhoondta hoon.\n"
                    "Neeche diye gaye buttons se settings manage karein.")
        
        if update.message:
            await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        print(f"Start command error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        global FILTER_MTF, FILTER_VOLUME, FILTER_RSI, active_trades
        
        if query.data == 'settings':
            keyboard = [
                [InlineKeyboardButton(f"MTF Trend Filter: {'🟢 ON' if FILTER_MTF else '🔴 OFF'}", callback_data='toggle_mtf')],
                [InlineKeyboardButton(f"Volume Filter: {'🟢 ON' if FILTER_VOLUME else '🔴 OFF'}", callback_data='toggle_vol')],
                [InlineKeyboardButton(f"RSI Filter: {'🟢 ON' if FILTER_RSI else '🔴 OFF'}", callback_data='toggle_rsi')],
                [InlineKeyboardButton("🔙 Back", callback_data='main_menu')]
            ]
            await query.edit_message_text("⚙️ **Bot Settings**\nFilters ko on/off karne ke liye click karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        
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
            
        elif query.data == 'list_coins':
            await query.edit_message_text(f"📊 **Tracking Top Volume Coins on Bitget:**\n\n (Bot khud automatically top 10 high-volume coins fetch karta hai)", parse_mode='Markdown')
            
        elif query.data == 'status':
            await query.edit_message_text(f"📡 **Status**\nActive Trades in Memory: {len(active_trades)}\nSource: Bitget\nStatus: Running 🟢", parse_mode='Markdown')
            
        elif query.data == 'clear_trades':
            active_trades = {}
            save_state(active_trades)
            await query.edit_message_text("🗑️ **Active Trades Cleared!**\nAb bot naye sire se signals dhoondega.", parse_mode='Markdown')
    except Exception as e:
        print(f"Button handler error: {e}")

# ==========================================
# 5. DYNAMIC TOP VOLUME COINS FETCHER
# ==========================================
def get_top_volume_coins():
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = {symbol: data for symbol, data in tickers.items() if symbol.endswith('/USDT')}
        sorted_pairs = sorted(usdt_pairs.items(), key=lambda x: x[1].get('quoteVolume', 0) or 0, reverse=True)
        return [pair[0] for pair in sorted_pairs[:10]]
    except Exception as e:
        print(f"Error fetching top coins: {e}")
        return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT']

# ==========================================
# 6. SIGNAL ENGINE & FILTERS
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
        df['ATR'] = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14).average_true_range()
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
        c_atr = df['ATR'].iloc[-1]
        
        ema_cross_up = (p_ema9 <= p_ema21) and (c_ema9 > c_ema21)
        ema_cross_down = (p_ema9 >= p_ema21) and (c_ema9 < c_ema21)
        
        if ema_cross_up and c_adx > 25 and c_roc > 0:
            signal = "BUY"
        elif ema_cross_down and c_adx > 25 and c_roc < 0:
            signal = "SELL"
        else:
            return "WAIT", c_close, 0, "", 0, 0
            
        strength = 60 
        filter_details = ""
        
        if FILTER_MTF:
            mtf_trend = check_mtf_trend(symbol, timeframe)
            if (signal == "BUY" and mtf_trend == "BULLISH") or (signal == "SELL" and mtf_trend == "BEARISH"):
                strength += 15
                filter_details += f"✅ MTF Aligned ({mtf_trend})\n"
            else:
                return "WAIT", c_close, 0, "", 0, 0 
                
        if FILTER_VOLUME:
            if c_vol > (c_vol_sma * 1.5):
                strength += 15
                filter_details += f"✅ Volume Spike ({c_vol/c_vol_sma:.1f}x)\n"
            else:
                return "WAIT", c_close, 0, "", 0, 0 
                
        if FILTER_RSI:
            if signal == "BUY" and 45 < c_rsi < 70:
                strength += 10
                filter_details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            elif signal == "SELL" and 30 < c_rsi < 55:
                strength += 10
                filter_details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            else:
                return "WAIT", c_close, 0, "", 0, 0 

        sl_distance = c_atr * 1.5 
        if signal == "BUY":
            sl_price = c_close - sl_distance
            tp_price = c_close + (sl_distance * 2)
        else: 
            sl_price = c_close + sl_distance
            tp_price = c_close - (sl_distance * 2)

        return signal, c_close, strength, filter_details, sl_price, tp_price
        
    except Exception as e:
        print(f"Error on {symbol}: {e}")
        return "ERROR", 0, 0, "", 0, 0

# ==========================================
# 7. BACKGROUND SCANNER
# ==========================================
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    try:
        global active_trades
        top_coins = get_top_volume_coins()
        print(f"Scanning {len(top_coins)} coins...")
        
        for coin in top_coins:
            for tf in timeframes:
                signal, price, strength, details, sl_price, tp_price = check_signal(coin, tf)
                
                if signal == "WAIT" or signal == "ERROR":
                    continue
                    
                # --- SPOT ---
                if signal == "BUY":
                    spot_id = f"{coin}_{tf}_SPOT"
                    if spot_id not in active_trades:
                        active_trades[spot_id] = {"entry": price}
                        save_state(active_trades)
                        msg = (f"🟢 **SPOT BUY: {coin}** ({tf})\n"
                               f"⭐ **Strength: {strength}%**\n\n"
                               f"💵 Entry: {price}\n"
                               f"🎯 Target: {tp_price:.4f}\n"
                               f"🛑 SL: {sl_price:.4f}\n\n"
                               f"**Filters:**\n{details}")
                        try:
                            await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')
                        except:
                            pass # Agar message send na ho toh crash na ho

                # --- FUTURES ---
                fut_id = f"{coin}_{tf}_FUT"
                if signal == "BUY":
                    if fut_id not in active_trades:
                        active_trades[fut_id] = {"entry": price, "type": "LONG"}
                        save_state(active_trades)
                        msg = (f"🚀 **FUTURES LONG: {coin}** ({tf})\n"
                               f"⭐ **Strength: {strength}%**\n\n"
                               f"💵 Entry: {price}\n"
                               f"🎯 Target: {tp_price:.4f}\n"
                               f"🛑 SL: {sl_price:.4f}\n\n"
                               f"**Filters:**\n{details}")
                        try:
                            await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')
                        except:
                            pass
                        
                elif signal == "SELL":
                    if f"{fut_id}_SHORT" not in active_trades:
                        active_trades[f"{fut_id}_SHORT"] = {"entry": price, "type": "SHORT"}
                        save_state(active_trades)
                        msg = (f"🔴 **FUTURES SHORT: {coin}** ({tf})\n"
                               f"⭐ **Strength: {strength}%**\n\n"
                               f"💵 Entry: {price}\n"
                               f"🎯 Target: {tp_price:.4f}\n"
                               f"🛑 SL: {sl_price:.4f}\n\n"
                               f"**Filters:**\n{details}")
                        try:
                            await context.bot.send_message(chat_id=YOUR_CHAT_ID, text=msg, parse_mode='Markdown')
                        except:
                            pass
    except Exception as e:
        print(f"Scan loop error: {e}")

# ==========================================
# 8. MAIN (With Robust Conflict Handler)
# ==========================================
def main():
    # Flask ko background mein start karein
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Bot loop jo crash nahi hoga
    while True:
        try:
            print("Bot instance starting...")
            app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
            
            app_bot.add_handler(CommandHandler("start", start))
            app_bot.add_handler(CallbackQueryHandler(button_handler))
            
            job_queue = app_bot.job_queue
            job_queue.run_repeating(scan_market, interval=600, first=10)

            print("Professional V3.0 Bot is running...")
            app_bot.run_polling()
            
        except Exception as e:
            print(f"⚠️ Main Loop Error: {e}. Waiting 15 seconds before retry...")
            import time
            time.sleep(15) # Safe sleep
            continue

if __name__ == '__main__':
    main()
