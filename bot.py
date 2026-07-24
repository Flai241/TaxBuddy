import sqlite3
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

def init_db():
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            description TEXT,
            category TEXT,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_transaction(user_id, trans_type, amount, description, category):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO transactions (user_id, type, amount, description, category, date) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, trans_type, amount, description, category, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id = ? GROUP BY type", (user_id,))
    rows = dict(cursor.fetchall())
    conn.close()
    income = rows.get("income", 0)
    expense = rows.get("expense", 0)
    tax_base = income - expense
    tax = round(tax_base * 0.06, 2) if tax_base > 0 else 0
    return income, expense, tax_base, tax

main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("➕ Доход"), KeyboardButton("➖ Расход")],
    [KeyboardButton("📊 Баланс"), KeyboardButton("🧾 О налогах")],
    [KeyboardButton("ℹ️ Помощь")]
], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я TaxBuddy — твой налоговый помощник.\n\n"
        "Нажми «➕ Доход» или «➖ Расход», чтобы записать операцию.\n"
        "Или просто напиши сумму!",
        reply_markup=main_keyboard
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 Как пользоваться:\n\n"
        "• Нажми «➕ Доход» и введи сумму\n"
        "• Нажми «➖ Расход» и введи сумму\n"
        "• «📊 Баланс» — посчитать налог\n"
        "• «🧾 О налогах» — узнать про налоги\n\n"
        "Скоро я научусь понимать твои сообщения и чеки!",
        reply_markup=main_keyboard
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    income, expense, tax_base, tax = get_balance(user_id)
    await update.message.reply_text(
        f"📊 Твой баланс:\n\n"
        f"💰 Доходы: {income} ₽\n"
        f"💸 Расходы: {expense} ₽\n"
        f"📌 Налоговая база: {tax_base} ₽\n"
        f"🧾 Налог к уплате (6%): {tax} ₽\n\n"
        f"✅ Можно тратить: {income - expense - tax} ₽",
        reply_markup=main_keyboard
    )

async def tax_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧾 О налогах для самозанятых:\n\n"
        "• 4% — с доходов от физлиц\n"
        "• 6% — с доходов от юрлиц и ИП\n"
        "• Нет обязательных взносов\n"
        "• Лимит дохода: 2,4 млн ₽/год\n\n"
        "Оплата до 25 числа следующего месяца.\n"
        "Я считаю по ставке 6%.",
        reply_markup=main_keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "➕ Доход":
        context.user_data["mode"] = "income"
        await update.message.reply_text("Введи сумму дохода (только число):")
        return
    
    if text == "➖ Расход":
        context.user_data["mode"] = "expense"
        await update.message.reply_text("Введи сумму расхода (только число):")
        return
    
    if text == "📊 Баланс":
        await balance(update, context)
        return
    
    if text == "🧾 О налогах":
        await tax_info(update, context)
        return
    
    if text == "ℹ️ Помощь":
        await help_cmd(update, context)
        return
    
    mode = context.user_data.get("mode")
    if mode:
        try:
            amount = float(text.replace(",", ".").replace(" ", ""))
            if amount <= 0:
                await update.message.reply_text("Сумма должна быть больше нуля!")
                return
            
            if mode == "income":
                add_transaction(user_id, "income", amount, "Доход", "Работа")
                await update.message.reply_text(f"✅ Записал доход: {amount} ₽", reply_markup=main_keyboard)
            else:
                add_transaction(user_id, "expense", amount, "Расход", "Прочее")
                await update.message.reply_text(f"✅ Записал расход: {amount} ₽", reply_markup=main_keyboard)
            
            context.user_data["mode"] = None
        except ValueError:
            await update.message.reply_text("Введи только число! Например: 5000")
    else:
        await update.message.reply_text(
            "Используй кнопки «➕ Доход» или «➖ Расход»!",
            reply_markup=main_keyboard
        )

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
