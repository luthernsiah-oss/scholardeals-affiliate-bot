import os
import logging
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PRICE = float(os.getenv("FORM_PRICE"))
COMMISSION = float(os.getenv("COMMISSION"))

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE,
        username TEXT,
        referral_code TEXT,
        referred_by BIGINT,
        balance NUMERIC DEFAULT 0,
        total_earnings NUMERIC DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        university TEXT,
        status TEXT,
        screenshot TEXT,
        referrer BIGINT,
        commission_given BOOLEAN DEFAULT FALSE
    );
    """)
    conn.commit()

# ================= UTIL =================
def get_user(tg_id):
    cur.execute("SELECT * FROM users WHERE telegram_id=%s", (tg_id,))
    return cur.fetchone()

def create_user(user):
    ref_code = f"ref_{user.id}"
    cur.execute("""
    INSERT INTO users (telegram_id, username, referral_code)
    VALUES (%s, %s, %s)
    ON CONFLICT DO NOTHING
    """, (user.id, user.username, ref_code))
    conn.commit()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user)

    # referral tracking
    if context.args:
        ref = context.args[0]
        if ref.startswith("ref_"):
            ref_id = int(ref.split("_")[1])
            cur.execute("""
            UPDATE users SET referred_by=%s
            WHERE telegram_id=%s AND referred_by IS NULL
            """, (ref_id, user.id))
            conn.commit()

    keyboard = [
        ["🎓 Buy Forms"],
        ["🏆 Affiliate Dashboard"]
    ]

    await update.message.reply_text(
        "Welcome to ScholarDeals 🎓",
        reply_markup={"keyboard": keyboard, "resize_keyboard": True}
    )

# ================= BUY =================
universities = [
"UG","KNUST","UCC","UEW","UDS","UMaT","UHAS","UENR","UPSA",
"GIMPA","AAMUSTED","CKT-UTAS","SDD-UBIDS","UESD","GCTU","UniMAC",
"ATU","KsTU","KTU","CCTU","TTU","HTU","BTU"
]

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(u, callback_data=f"buy_{u}")] for u in universities]
    await update.message.reply_text("Select a university:", reply_markup=InlineKeyboardMarkup(keyboard))

async def select_uni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uni = query.data.split("_")[1]
    context.user_data["uni"] = uni

    await query.message.reply_text(
        f"Pay GH₵{PRICE} to:\n"
        f"0530790707\nFrank Nsiah\n\n"
        f"Send screenshot after payment"
    )

# ================= SCREENSHOT =================
async def screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uni = context.user_data.get("uni")

    if not uni:
        return

    file_id = update.message.photo[-1].file_id

    cur.execute("SELECT referred_by FROM users WHERE telegram_id=%s", (user.id,))
    ref = cur.fetchone()[0]

    cur.execute("""
    INSERT INTO orders (user_id, university, status, screenshot, referrer)
    VALUES (%s, %s, 'pending', %s, %s) RETURNING id
    """, (user.id, uni, file_id, ref))
    order_id = cur.fetchone()[0]
    conn.commit()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{order_id}")
        ]
    ])

    await context.bot.send_photo(
        ADMIN_ID,
        file_id,
        caption=f"New Order #{order_id}\n{uni}",
        reply_markup=keyboard
    )

    await update.message.reply_text("Payment received. Waiting for approval.")

# ================= APPROVE =================
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    order_id = int(query.data.split("_")[1])

    cur.execute("SELECT user_id, referrer FROM orders WHERE id=%s", (order_id,))
    user_id, ref = cur.fetchone()

    cur.execute("UPDATE orders SET status='approved' WHERE id=%s", (order_id,))

    # commission
    if ref:
        cur.execute("""
        UPDATE users
        SET balance = balance + %s,
            total_earnings = total_earnings + %s
        WHERE telegram_id=%s
        """, (COMMISSION, COMMISSION, ref))

    conn.commit()

    await context.bot.send_message(user_id, "✅ Payment approved. Your form will be sent shortly.")

    await query.edit_message_caption("Approved ✅")

# ================= DASHBOARD =================
async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    cur.execute("""
    SELECT balance, total_earnings FROM users WHERE telegram_id=%s
    """, (user.id,))
    data = cur.fetchone()

    balance, total = data if data else (0, 0)

    link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"

    text = f"""
🏆 Affiliate Dashboard

💰 Balance: GH₵{balance}
🎯 Total Earnings: GH₵{total}

🔗 Your Link:
{link}
"""

    await update.message.reply_text(text)

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Buy"), buy))
    app.add_handler(CallbackQueryHandler(select_uni, pattern="buy_"))
    app.add_handler(MessageHandler(filters.PHOTO, screenshot))
    app.add_handler(CallbackQueryHandler(approve, pattern="approve_"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Affiliate"), dashboard))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
