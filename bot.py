import sqlite3
from datetime import datetime
import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import json
import sys
import time
time.sleep(3)

BOT_TOKEN = "8969477388:AAEhJtwkM3_wu8kL-JWse3bxYg6DPR-8_iE"
GEMINI_KEY = os.environ.get("GEMINI_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

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

def parse_message(text):
    prompt = f"""Ты — бухгалтерский ассистент. Проанализируй сообщение и верни ТОЛЬКО JSON без пояснений.
Сообщение: "{text}"
Формат: {{"type": "income" или "expense", "amount": число, "description": "краткое описание", "category": "категория"}}
Категории: Работа, Подписки, Транспорт, Еда, Офис, Маркетинг, Прочее.
Если сумма не указана, поставь 0. Если не понятно доход или расход — ставь "expense"."""
    
    response = model.generate_content(prompt)
    return response.text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я TaxBuddy — твой налоговый помощник.\n\n"
        "Напиши мне о доходах или расходах, например:\n"
        "«Заработал 5000 рублей за логотип»\n"
        "«Купил подписку за 599 рублей»\n\n"
        "Команды:\n"
        "/balance — узнать баланс и налог\n"
        "/help — помощь"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Просто пиши мне в свободной форме:\n"
        "• «Получил 10 000 от клиента»\n"
        "• «Оплатил интернет 500 руб»\n"
        "• «Обед с заказчиком 1200»\n\n"
        "/balance — посчитать налог 6%"
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
        f"✅ Безопасно можно тратить: {income - expense - tax} ₽"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    try:
        result = parse_message(text)
        result = result.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(result)
        
        trans_type = data.get("type", "expense")
        amount = float(data.get("amount", 0))
        description = data.get("description", text)
        category = data.get("category", "Прочее")
        
        if amount == 0:
            await update.message.reply_text("🤔 Не понял сумму. Напиши, сколько денег, например: «Заработал 5000 рублей»")
            return
        
        add_transaction(user_id, trans_type, amount, description, category)
        
        emoji = "➕" if trans_type == "income" else "➖"
        await update.message.reply_text(
            f"{emoji} Записал: {description}\n"
            f"Сумма: {amount} ₽\n"
            f"Категория: {category}\n\n"
            f"Напиши /balance чтобы узнать налог"
        )
    except Exception as e:
        await update.message.reply_text("😵 Что-то пошло не так. Попробуй написать иначе, например: «Заработал 5000 рублей за дизайн»")

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
