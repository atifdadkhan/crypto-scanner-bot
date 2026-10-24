import os
import json
import ccxt
import pandas as pd
import ta
import threading
import asyncio
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

tracked_coins = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'MATIC/USDT'
]
timeframes = ['1h', '4h']

# Filters
FILTER_CORE = True
FILTER_MTF = True
FILTER_VOLUME = True
FILTER_RSI = True

# Global Locks
is_scanning = False # Prevents double clicking scan button

# ==========================================
# 2. FLASK WEB SERVER (Keep-Alive)
# ==========================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 3. STATE MANAGEMENT (Corruption Safe)
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("⚠️ State file corrupted. Resetting...")
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"⚠️ Could not save state: {e}")

active_trades = load_state()

# ==========================================
# 4. ERROR HANDLER
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"⚠️ Global Error: {context.error}")

# ==========================================
# 5. TELEGRAM UI HELPERS
# ==========================================
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Active Trades", callback_data='active_trades'), 
         InlineKeyboardButton("🌐 Market Summary", callback_data='market_summary')],
        [InlineKeyboardButton("🔎 Scan Top 100 Market", callback_data='scan_top_100')],
        [InlineKeyboardButton("🔍 Analyze Coin", callback_data='analyze_coin')],
        [InlineKeyboardButton("📊 Manage Coins", callback_data='manage_coins')],
        [InlineKeyboardButton("⚙️ Settings", callback_data='settings'), 
         InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]
    text = (
        "💼 <b>PRO TRADING TERMINAL</b> 💼\n\n"
        "Welcome Boss! Main aapka personal trading assistant hoon.\n"
        "Neeche diye gaye menu se apna kaam manage karein.\n\n"
        "⚡ <i>Pullback Entry | 1:2 RR | Partial Booking</i>"
    )
    return text, InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ <b>Access Denied.</b>\nThis is a private bot.", parse_mode='HTML')
        return

    text, reply_markup = get_main_menu()
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

# ==========================================
# 6. BACKGROUND MARKET SCANNER LOGIC
# ==========================================
def run_market_scan():
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = {k: v for k, v in tickers.items() if k.endswith('/USDT') and v.get('quoteVolume')}
        
        # Top 100 by volume
        sorted_pairs = sorted(usdt_pairs.items(), key=lambda x: x[1]['quoteVolume'], reverse=True)
        top_100_coins = [k for k, v in sorted_pairs[:100]]

        results = []
        
        for coin in top_100_coins:
            signal, price, details = check_signal(coin, '1h')
            
            if signal in ["BUY", "SELL"]:
                if signal == "BUY":
                    sl, tp1 = price * 0.985, price * 1.03 
                    direction = "🟢 LONG"
                else:
                    sl, tp1 = price * 1.015, price * 0.97 
                    direction = "🔴 SHORT"
                
                results.append({"coin": coin, "signal": direction, "price": price, "sl": sl, "tp1": tp1})
        
        if not results:
            return "🔎 <b>Market Scan Complete</b>\n\nTop 100 coins mein abhi koi clear signal nahi mila. WAIT karein."
            
        result_text = "🚀 <b>TOP 100 MARKET SCAN</b>\n\n"
        result_text += "Yeh woh coins hain jahan abhi trade ban rahi hai:\n\n"
        
        for res in results:
            result_text += f"<b>{res['coin']}</b> ({res['signal']})\n"
            result_text += f"💵 Entry: <code>{res['price']:.4f}</code>\n"
            result_text += f"🛑 SL: <code>{res['sl']:.4f}</code> | 🎯 TP1: <code>{res['tp1']:.4f}</code>\n\n"
            
        result_text += "<i>Note: Yeh 1H timeframe ka scan hai. Entry se pehle chart confirm karein.</i>"
        return result_text
        
    except Exception as e:
        print(f"Scan Error: {e}")
        return f"❌ Market scan mein error aya: {e}"

# ==========================================
# 7. BUTTON HANDLER
# ==========================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_scanning, FILTER_CORE, FILTER_MTF, FILTER_VOLUME, FILTER_RSI
    
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id != ADMIN_ID:
        await query.answer("⛔ Access Denied.", show_alert=True)
        return
        
    await query.answer()
    
    if query.data == 'main_menu':
        text, reply_markup = get_main_menu()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # --- SCAN TOP 100 (Lock Protected) ---
    elif query.data == 'scan_top_100':
        if is_scanning:
            await query.answer("⏳ A scan is already in progress. Please wait...", show_alert=True)
            return
            
        is_scanning = True
        await query.edit_message_text("⏳ <b>Scanning Top 100 Coins by Volume...</b>\n\nPlease wait 1-2 minutes. Main result tayar karke bhej raha hoon...", parse_mode='HTML')
        
        try:
            result_text = await asyncio.to_thread(run_market_scan)
            await query.edit_message_text(result_text, 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Scan Again", callback_data='scan_top_100'), InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), 
                                          parse_mode='HTML')
        finally:
            is_scanning = False # Lock Release

    # --- ACTIVE TRADES (Lightweight API) ---
    elif query.data == 'active_trades':
        if not active_trades:
            await query.edit_message_text("📭 <b>No Active Trades.</b>\nBot abhi kisi trade ko track nahi kar raha.", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')
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
            
            # FAST API FIX: fetch_ticker instead of fetch_ohlcv
            try:
                current_price = exchange.fetch_ticker(trade['coin'])['last']
            except Exception:
                current_price = entry
                
            status = "🟢 In Profit" if (direction == "LONG" and current_price > entry) or (direction == "SHORT" and current_price < entry) else "🔴 In Loss"
            
            text += f"<b>{coin} ({tf}) {direction}</b>\n"
            text += f"Entry: <code>{entry:.4f}</code> | Current: <code>{current_price:.4f}</code>\n"
            text += f"SL: <code>{sl:.4f}</code> | TP1: <code>{tp1:.4f}</code>\n"
            text += f"Status: {status}\n\n"
            
            keyboard.append([InlineKeyboardButton(f"❌ Cancel {coin}", callback_data=f"cancel_{trade_id}")])
            
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='main_menu')])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    elif query.data.startswith('cancel_'):
        trade_id = query.data.replace('cancel_', '')
        if trade_id in active_trades:
            del active_trades[trade_id]
            save_state(active_trades)
        await query.edit_message_text(f"🗑️ Trade <code>{trade_id}</code> cancelled successfully.", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='active_trades')]]), parse_mode='HTML')

    # --- MARKET SUMMARY ---
    elif query.data == 'market_summary':
        await query.edit_message_text("⏳ Fetching Market Summary...")
        summary_text = "🌐 <b>TOP COINS TREND (1H)</b>\n\n"
        for coin in tracked_coins[:10]:
            signal, price, details = check_signal(coin, '1h')
            trend = "🟢 BULLISH" if signal == "BUY" else "🔴 BEARISH" if signal == "SELL" else "🟡 WAIT"
            summary_text += f"<b>{coin}</b>: {trend}\n"
            
        summary_text += "\n<i>Yeh analysis MTF aur Core filters ke hisaab se hai.</i>"
        await query.edit_message_text(summary_text, 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh", callback_data='market_summary'), InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

    # --- ANALYZE COIN ---
    elif query.data == 'analyze_coin':
        await query.edit_message_text("🔍 <b>Coin Analysis</b>\n\nPlease send the coin name like this:\n<code>BTC/USDT</code>\n\nOr simply type: <code>BTC</code>", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')
        context.user_data['awaiting_coin'] = True

    # --- MANAGE COINS ---
    elif query.data == 'manage_coins':
        coins_list = "\n".join([f"• {coin}" for coin in tracked_coins])
        text = f"📊 <b>Tracked Coins ({len(tracked_coins)}):</b>\n{coins_list}\n\n"
        text += "<b>Add:</b> <code>/add DOGE</code>\n<b>Remove:</b> <code>/remove DOGE</code>"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

    # --- SETTINGS ---
    elif query.data == 'settings':
        keyboard = [
            [InlineKeyboardButton(f"Core Strategy: {'🟢 ON' if FILTER_CORE else '🔴 OFF'}", callback_data='toggle_core')],
            [InlineKeyboardButton(f"MTF Trend: {'🟢 ON' if FILTER_MTF else '🔴 OFF'}", callback_data='toggle_mtf')],
            [InlineKeyboardButton(f"Volume Filter: {'🟢 ON' if FILTER_VOLUME else '🔴 OFF'}", callback_data='toggle_vol')],
            [InlineKeyboardButton(f"RSI Filter: {'🟢 ON' if FILTER_RSI else '🔴 OFF'}", callback_data='toggle_rsi')],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]
        ]
        await query.edit_message_text("⚙️ <b>Terminal Settings</b>\n\nFilters ON/OFF karne ke liye click karein.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data == 'toggle_core':
        FILTER_CORE = not FILTER_CORE; await button_handler(update, context) 
    elif query.data == 'toggle_mtf':
        FILTER_MTF = not FILTER_MTF; await button_handler(update, context)
    elif query.data == 'toggle_vol':
        FILTER_VOLUME = not FILTER_VOLUME; await button_handler(update, context)
    elif query.data == 'toggle_rsi':
        FILTER_RSI = not FILTER_RSI; await button_handler(update, context)

    # --- HELP ---
    elif query.data == 'help':
        help_text = (
            "ℹ️ <b>Terminal Guide</b>\n\n"
            "1️⃣ <b>Scan Top 100:</b> Market ke top 100 coins scan karein.\n"
            "2️⃣ <b>Active Trades:</b> Live positions ka status.\n"
            "3️⃣ <b>Analyze Coin:</b> Kisi ek coin ka manual analysis.\n"
            "4️⃣ <b>Manage Coins:</b> <code>/add</code> ya <code>/remove</code> se coins manage karein.\n\n"
            "<b>Strategy:</b> 1.5% SL, 3% TP1, Trailing SL to Breakeven."
        )
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='main_menu')]]), parse_mode='HTML')

# ==========================================
# 8. MESSAGE HANDLER (Manual Coin Analysis)
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return

    if context.user_data.get('awaiting_coin'):
        context.user_data['awaiting_coin'] = False
        coin = update.message.text.strip().upper()
        
        if not coin.endswith('/USDT'): 
            coin += '/USDT'
            
        msg = await update.message.reply_text(f"🔍 Analyzing <b>{coin}</b>...", parse_mode='HTML')
        
        signal, price, details = check_signal(coin, '1h')
        
        if signal == "ERROR":
            await msg.edit_text(f"❌ Error fetching data for <b>{coin}</b>. Make sure it exists on Bitget.", parse_mode='HTML')
            return
            
        report = (f"<b>Analysis: {coin} (1H)</b>\n"
                  f"💵 Current Price: <code>{price:.4f}</code>\n"
                  f"📊 Status: <b>{signal}</b>\n\n"
                  f"<b>Conditions Met:</b>\n{details}")
                  
        await msg.edit_text(report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data='main_menu')]]), parse_mode='HTML')
    else:
        await update.message.reply_text("Please use the /start menu to navigate the terminal.")

# ==========================================
# 9. COMMANDS (/add, /remove)
# ==========================================
async def add_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        coin = context.args[0].upper()
        if not coin.endswith('/USDT'): coin += '/USDT'
        if coin not in tracked_coins:
            tracked_coins.append(coin)
            await update.message.reply_text(f"✅ Added <b>{coin}</b> to scanner.", parse_mode='HTML')
        else:
            await update.message.reply_text(f"⚠️ {coin} is already in list.")
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
# 10. SIGNAL ENGINE
# ==========================================
def check_mtf_trend(symbol, current_tf):
    try:
        check_tf = '4h' if current_tf == '1h' else '1d'
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
        c_low = df['low'].iloc[-1]
        c_high = df['high'].iloc[-1]
        
        c_ema9 = df['EMA9'].iloc[-1]
        c_ema21 = df['EMA21'].iloc[-1]
        p_ema9 = df['EMA9'].iloc[-2]
        p_ema21 = df['EMA21'].iloc[-2]
        c_adx = df['ADX'].iloc[-1]
        p_adx = df['ADX'].iloc[-2]
        c_roc = df['ROC'].iloc[-1]
        c_rsi = df['RSI'].iloc[-1]
        c_vol = df['volume'].iloc[-1]
        c_vol_sma = df['Vol_SMA'].iloc[-1]
        
        if not FILTER_CORE:
            return "WAIT", c_close, "❌ Core Strategy OFF."

        signal = "WAIT"
        details = ""
        
        bullish_cross = (p_ema9 <= p_ema21) and (c_ema9 > c_ema21)
        bearish_cross = (p_ema9 >= p_ema21) and (c_ema9 < c_ema21)
        
        bullish_pullback = (c_low <= c_ema9) and (c_close > c_ema9)
        bearish_pullback = (c_high >= c_ema9) and (c_close < c_ema9)
        
        adx_rising = c_adx > p_adx and c_adx > 20

        if (bullish_cross or bullish_pullback) and c_ema9 > c_ema21 and adx_rising and c_roc > 0:
            signal = "BUY"
            details += f"✅ EMA Bullish + Pullback\n✅ ADX Rising ({c_adx:.1f})\n✅ ROC Positive\n"
        elif (bearish_cross or bearish_pullback) and c_ema9 < c_ema21 and adx_rising and c_roc < 0:
            signal = "SELL"
            details += f"✅ EMA Bearish + Pullback\n✅ ADX Rising ({c_adx:.1f})\n✅ ROC Negative\n"
        else:
            return "WAIT", c_close, "❌ No valid Pullback or ADX not rising."

        if FILTER_MTF:
            mtf = check_mtf_trend(symbol, timeframe)
            if (signal == "BUY" and mtf == "BULLISH") or (signal == "SELL" and mtf == "BEARISH"):
                details += f"✅ MTF Aligned ({mtf})\n"
            else:
                return "WAIT", c_close, details + f"❌ MTF Conflict."

        if FILTER_VOLUME:
            if c_vol > (c_vol_sma * 1.2):
                details += f"✅ Volume Confirmed\n"
            else:
                return "WAIT", c_close, details + f"❌ Low Volume."

        if FILTER_RSI:
            if signal == "BUY" and 40 < c_rsi < 70:
                details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            elif signal == "SELL" and 30 < c_rsi < 60:
                details += f"✅ RSI Safe ({c_rsi:.1f})\n"
            else:
                return "WAIT", c_close, details + f"❌ RSI Extreme."

        return signal, c_close, details
        
    except Exception as e:
        return "ERROR", 0, ""

# ==========================================
# 11. BACKGROUND SCANNER & TRADE MANAGER
# ==========================================
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    global active_trades
    
    for coin in tracked_coins:
        for tf in timeframes:
            signal, price, details = check_signal(coin, tf)
            
            if signal in ["BUY", "SELL"]:
                trade_id = f"{coin}_{tf}_{signal}"
                if trade_id not in active_trades:
                    if signal == "BUY":
                        sl, tp1, tp2 = price * 0.985, price * 1.03, price * 1.06
                        emoji, direction = "🟢", "LONG"
                    else:
                        sl, tp1, tp2 = price * 1.015, price * 0.97, price * 0.94
                        emoji, direction = "🔴", "SHORT"
                    
                    active_trades[trade_id] = {
                        "coin": coin, "entry": price, "sl": sl, "tp1": tp1, "tp2": tp2, 
                        "type": direction, "tp1_hit": False, "sl_moved": False
                    }
                    save_state(active_trades)
                    
                    msg = (f"{emoji} <b>{direction}: {coin}</b> ({tf})\n\n"
                           f"💵 Entry: <code>{price:.4f}</code>\n"
                           f"🛑 SL: <code>{sl:.4f}</code>\n"
                           f"🎯 TP1 (50%): <code>{tp1:.4f}</code>\n"
                           f"🎯 TP2 (50%): <code>{tp2:.4f}</code>\n\n"
                           f"<b>Details:</b>\n{details}")
                    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')

    for trade_id, trade in list(active_trades.items()):
        # FAST API FIX: fetch_ticker instead of fetch_ohlcv
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
                msg = (f"🎯 <b>TP1 HIT: {trade['coin']}</b>\n\n"
                       f"✅ 50% Booked. SL moved to Breakeven (<code>{entry:.4f}</code>).")
                await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='HTML')
        
        if (direction == "LONG" and current_price >= tp2) or (direction == "SHORT" and current_price <= tp2):
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🏆 <b>TP2 HIT: {trade['coin']}</b>\n✅ Full Trade Closed.", parse_mode='HTML')
            del active_trades[trade_id]
            save_state(active_trades)
            continue

        if (direction == "LONG" and current_price <= sl) or (direction == "SHORT" and current_price >= sl):
            status = "Breakeven" if trade['sl_moved'] else "Loss (-1.5%)"
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔴 <b>SL HIT: {trade['coin']}</b>\n❌ Closed at {status}.", parse_mode='HTML')
            del active_trades[trade_id]
            save_state(active_trades)

# ==========================================
# 12. MAIN
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
    job_queue.run_repeating(scan_market, interval=300, first=10)

    print("Ultimate Terminal Bot is running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
