import requests
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import threading
import time

# إعداد تسجيل الدخول
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# تخزين الأكواد وصلاحيات المستخدمين
valid_codes = {}
user_access = {}

# دالة لحساب EMA (المتوسط المتحرك الأسي)
def calculate_ema(prices, period):
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]  # بدء EMA بحساب المتوسط البسيط للفترة الأولى
    for price in prices[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

# دالة لحساب RSI (مؤشر القوة النسبية)
def calculate_rsi(prices, period):
    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            losses.append(-change)
            gains.append(0)

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return rsi

# دالة لجلب بيانات العملة من Binance API
def get_crypto_analysis(symbol, interval='1d', strategy='ema'):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        response = requests.get(url)
        response.raise_for_status()  # للتحقق من حالة الاستجابة
        data = response.json()

        if not data:
            logging.warning(f"No data returned for {symbol}.")
            return None, None, None, None, None, None
        
        closes = [float(candle[4]) for candle in data]
        current_price = closes[-1]

        signal = ""
        take_profit = None
        stop_loss = None
        entry_price = current_price
        direction = ""

        # اختيار الاستراتيجية
        if strategy == 'ema':
            ema_20 = calculate_ema(closes, 20)

            # استراتيجية الشراء
            if current_price < ema_20[-1]:
                signal = "🔵 إشارة شراء بناءً على EMA.\n"
                take_profit = entry_price * 1.03
                stop_loss = entry_price * 0.97
                direction = "صاعد"
            # استراتيجية البيع
            elif current_price > ema_20[-1]:
                signal = "🔴 إشارة بيع بناءً على EMA.\n"
                take_profit = entry_price * 0.97
                stop_loss = entry_price * 1.03
                direction = "هابط"

        elif strategy == 'rsi':
            rsi = calculate_rsi(closes, 14)  # فترة 14 يوم
            if rsi < 30:
                signal = "🔵 إشارة شراء بناءً على RSI (تشبع بيع).\n"
                direction = "صاعد"
            elif rsi > 70:
                signal = "🔴 إشارة بيع بناءً على RSI (تشبع شراء).\n"
                direction = "هابط"
            else:
                signal = "⚪️ السوق في حالة توازن.\n"
                direction = "محايد"

        risk_reward_ratio = 2  # نسبة المخاطرة/العائد

        return signal, entry_price, take_profit, stop_loss, risk_reward_ratio, direction

    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    return None, None, None, None, None, None

# دالة لاستجابة الأوامر
async def start(update: Update, context):
    user_id = update.message.from_user.id
    if user_id in user_access and user_access[user_id]['valid']:
        keyboard = [
            [InlineKeyboardButton("بحث عن عملة", callback_data='search')],
            [InlineKeyboardButton("BTC/USDT", callback_data='BTCUSDT')],
            [InlineKeyboardButton("ETH/USDT", callback_data='ETHUSDT')],
            [InlineKeyboardButton("BNB/USDT", callback_data='BNBUSDT')],
            [InlineKeyboardButton("استراتيجيات التداول", callback_data='strategies')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('اختر العملة الرقمية لتحليل الصفقة أو ابحث عن عملة أو اختر استراتيجية:', reply_markup=reply_markup)
    else:
        await update.message.reply_text("يرجى إدخال كود الوصول لاستخدام البوت. استخدم الأمر /access [الكود]")

# دالة لإنشاء الكود بواسطة الأدمن
async def create_code(update: Update, context):
    if update.message.from_user.id == 408684267:  # معرف الأدمن
        try:
            code = context.args[0]
            duration = int(context.args[1])  # مدة الصلاحية بالدقائق
            valid_codes[code] = time.time() + (duration * 60)
            await update.message.reply_text(f"✅ تم إنشاء كود: {code} لمدة {duration} دقيقة.")
        except (IndexError, ValueError):
            await update.message.reply_text("الرجاء إدخال الكود والمدة بشكل صحيح. الاستخدام: /create_code [الكود] [المدة بالدقائق]")
    else:
        await update.message.reply_text("❌ ليس لديك صلاحيات لإصدار أكواد.")

# دالة لتفعيل الكود للمستخدم
async def access_code(update: Update, context):
    try:
        code = context.args[0]
        user_id = update.message.from_user.id
        if code in valid_codes and time.time() < valid_codes[code]:
            user_access[user_id] = {'valid': True, 'expires_at': valid_codes[code]}
            await update.message.reply_text("✅ تم تفعيل الكود. يمكنك الآن استخدام البوت.")
        else:
            await update.message.reply_text("❌ الكود غير صالح أو منتهي الصلاحية.")
    except IndexError:
        await update.message.reply_text("❌ الرجاء إدخال كود صالح. الاستخدام: /access [الكود]")

# دالة مراقبة انتهاء صلاحية الأكواد
def monitor_access():
    while True:
        current_time = time.time()
        expired_users = [user_id for user_id, data in user_access.items() if data['expires_at'] <= current_time]
        for user_id in expired_users:
            user_access[user_id]['valid'] = False
        time.sleep(60)

# دالة استجابة الأزرار
async def button(update: Update, context):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id in user_access and user_access[user_id]['valid']:
        # تحليل العملات وفقاً للزر
        pass  # يمكنك إضافة الكود هنا
    else:
        await query.edit_message_text(text="❌ الكود غير صالح أو منتهي الصلاحية. الرجاء إدخال كود صالح.")
    
# إعداد التطبيق الأساسي
def main():
    # بناء تطبيق التيلجرام
    application = ApplicationBuilder().token('7552362398:AAFFn72QDRBsPwigKsWFxeKvkBpqy1Oou8k').build()

    # إضافة أوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create_code", create_code))
    application.add_handler(CommandHandler("access", access_code))
    application.add_handler(CallbackQueryHandler(button))

    # تشغيل مراقبة الأكواد في الخلفية
    threading.Thread(target=monitor_access, daemon=True).start()

    # تشغيل البوت
    application.run_polling()

# نقطة البداية لتشغيل البوت
if __name__ == '__main__':
    main()