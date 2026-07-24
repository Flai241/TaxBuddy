import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8381828847:AAFaWP-IXVvdVJSpEac1hciXRWOAidHTHT0"

MAX_AMOUNT = 10_000_000
SELF_EMPLOYED_LIMIT = 2_400_000

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            tax_rate REAL DEFAULT 6.0
        )
    """)
    conn.commit()
    conn.close()

def get_tax_rate(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT tax_rate FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    else:
        conn = sqlite3.connect("taxbuddy.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, tax_rate) VALUES (?, 6.0)", (user_id,))
        conn.commit()
        conn.close()
        return 6.0

def set_tax_rate(user_id, rate):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, tax_rate) VALUES (?, ?)", (user_id, rate))
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
    last_id = cursor.lastrowid
    conn.close()
    return last_id

def delete_last_transaction(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, type, amount, description, category FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM transactions WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return row[1], row[2], row[3], row[4]
    conn.close()
    return None

def get_balance(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id = ? GROUP BY type", (user_id,))
    rows = dict(cursor.fetchall())
    conn.close()
    income = rows.get("income", 0)
    expense = rows.get("expense", 0)
    tax_rate = get_tax_rate(user_id)
    tax = round(income * tax_rate / 100, 2)
    net = income - tax - expense
    return income, expense, tax, net, tax_rate

def get_year_income(user_id):
    year_start = f"{datetime.now().year}-01-01"
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'income' AND date >= ?", (user_id, year_start))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row[0] else 0

def get_stats(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT strftime('%Y-%m', date) as month, SUM(amount) 
        FROM transactions 
        WHERE user_id = ? AND type = 'income' 
        GROUP BY month 
        ORDER BY month DESC 
        LIMIT 6
    """, (user_id,))
    income_by_month = cursor.fetchall()
    
    cursor.execute("""
        SELECT category, SUM(amount) 
        FROM transactions 
        WHERE user_id = ? AND type = 'expense' 
        GROUP BY category 
        ORDER BY SUM(amount) DESC
    """, (user_id,))
    expense_by_category = cursor.fetchall()
    
    cursor.execute("""
        SELECT category, SUM(amount) 
        FROM transactions 
        WHERE user_id = ? AND type = 'income' 
        GROUP BY category 
        ORDER BY SUM(amount) DESC
    """, (user_id,))
    income_by_category = cursor.fetchall()
    
    cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id = ? GROUP BY type", (user_id,))
    rows = dict(cursor.fetchall())
    conn.close()
    
    total_income = rows.get("income", 0)
    total_expense = rows.get("expense", 0)
    tax_rate = get_tax_rate(user_id)
    total_tax = round(total_income * tax_rate / 100, 2)
    
    return income_by_month, expense_by_category, income_by_category, total_income, total_expense, total_tax, tax_rate

def draw_chart(data, max_width=15):
    if not data:
        return "Нет данных"
    
    max_value = max([row[1] for row in data])
    if max_value == 0:
        return "Нет данных"
    
    lines = []
    for label, value in data:
        bar_width = int((value / max_value) * max_width) if max_value > 0 else 0
        bar = "█" * bar_width
        lines.append(f"{label}: {bar} {format_amount(value)} ₽")
    
    return "\n".join(lines)

def reset_user_data(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def format_amount(amount):
    if amount >= 0:
        return f"{amount:,.0f}".replace(",", " ")
    else:
        return f"-{abs(amount):,.0f}".replace(",", " ")

def export_report(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT type, amount, description, category, date FROM transactions WHERE user_id = ? ORDER BY date DESC LIMIT 100", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    income, expense, tax, net, tax_rate = get_balance(user_id)
    year_income = get_year_income(user_id)
    limit_left = SELF_EMPLOYED_LIMIT - year_income if tax_rate in [4.0, 6.0] else None
    
    report = "📄 ОТЧЁТ TAXBUDDY\n"
    report += f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
    report += f"Ставка налога: {tax_rate}%\n\n"
    report += f"💰 Всего доходов: {format_amount(income)} ₽\n"
    report += f"💸 Всего расходов: {format_amount(expense)} ₽\n"
    report += f"🧾 Налог к уплате: {format_amount(tax)} ₽\n"
    report += f"✅ Чистый остаток: {format_amount(net)} ₽\n"
    
    if limit_left is not None:
        report += f"\n📊 До лимита (2,4 млн): {format_amount(limit_left)} ₽\n"
    
    report += "\n━━━━━━━━━━━━━━━━\n📋 ПОСЛЕДНИЕ ОПЕРАЦИИ:\n\n"
    
    for row in rows:
        trans_type, amount, description, category, date = row
        emoji = "➕" if trans_type == "income" else "➖"
        report += f"{emoji} {format_amount(amount)} ₽ | {category} | {description} | {date}\n"
    
    return report

main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("➕ Доход"), KeyboardButton("➖ Расход")],
    [KeyboardButton("📊 Баланс"), KeyboardButton("📊 Статистика")],
    [KeyboardButton("🧾 О налогах"), KeyboardButton("ℹ️ Помощь")],
    [KeyboardButton("⚙️ Ставка налога"), KeyboardButton("📥 Экспорт")],
    [KeyboardButton("↩️ Отменить"), KeyboardButton("🔄 Сброс")]
], resize_keyboard=True)

category_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🚕 Такси"), KeyboardButton("📱 Подписки")],
    [KeyboardButton("🍔 Еда"), KeyboardButton("💼 Офис")],
    [KeyboardButton("📢 Маркетинг"), KeyboardButton("📦 Прочее")],
    [KeyboardButton("❌ Отмена")]
], resize_keyboard=True)

cancel_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("❌ Отмена")]
], resize_keyboard=True)

tax_rate_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("4% (самозанятый, физлица)")],
    [KeyboardButton("6% (самозанятый, юрлица/ИП)")],
    [KeyboardButton("13% (НДФЛ)")],
    [KeyboardButton("❌ Отмена")]
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
        "• Нажми «➖ Расход», введи сумму и выбери категорию\n"
        "• «📊 Баланс» — посчитать налог\n"
        "• «📊 Статистика» — графики и анализ\n"
        "• «⚙️ Ставка налога» — выбрать 4%, 6% или 13%\n"
        "• «📥 Экспорт» — скачать отчёт\n"
        "• «↩️ Отменить» — отменить последнюю операцию\n"
        "• «🔄 Сброс» — удалить все данные\n\n"
        "Скоро я научусь понимать твои сообщения и чеки!",
        reply_markup=main_keyboard
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    income, expense, tax, net, tax_rate = get_balance(user_id)
    year_income = get_year_income(user_id)
    
    warning = ""
    if net < 0:
        warning += f"\n\n⚠️ Твои расходы ({format_amount(expense)} ₽) превышают чистый доход. Ты в минусе на {format_amount(abs(net))} ₽."
    
    limit_info = ""
    if tax_rate in [4.0, 6.0]:
        limit_left = SELF_EMPLOYED_LIMIT - year_income
        percent = round((year_income / SELF_EMPLOYED_LIMIT) * 100, 1)
        limit_info = f"\n\n📊 Лимит самозанятого:\nИспользовано: {format_amount(year_income)} ₽ ({percent}%)\nОсталось: {format_amount(limit_left)} ₽"
        if limit_left < 0:
            limit_info += "\n⚠️ Лимит превышен!"
    
    await update.message.reply_text(
        f"📊 Твой баланс:\n\n"
        f"💰 Доходы: {format_amount(income)} ₽\n"
        f"💸 Расходы: {format_amount(expense)} ₽\n"
        f"🧾 Налог к уплате ({tax_rate}%): {format_amount(tax)} ₽\n\n"
        f"✅ Чистый остаток: {format_amount(net)} ₽"
        f"{limit_info}"
        f"{warning}",
        reply_markup=main_keyboard
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    income_by_month, expense_by_category, income_by_category, total_income, total_expense, total_tax, tax_rate = get_stats(user_id)
    
    if total_income == 0 and total_expense == 0:
        await update.message.reply_text(
            "📊 У тебя пока нет данных для статистики. Добавь доходы и расходы!",
            reply_markup=main_keyboard
        )
        return
    
    income_chart = draw_chart(income_by_month[::-1])
    expense_chart = draw_chart(expense_by_category)
    income_cat_chart = draw_chart(income_by_category)
    
    months_count = len(income_by_month) if income_by_month else 1
    avg_income = total_income / months_count if months_count > 0 else total_income
    
    await update.message.reply_text(
        f"📊 Статистика:\n\n"
        f"📈 Доходы по месяцам:\n{income_chart}\n\n"
        f"💰 Доходы по категориям:\n{income_cat_chart}\n\n"
        f"📂 Расходы по категориям:\n{expense_chart}\n\n"
        f"💵 Общий доход: {format_amount(total_income)} ₽\n"
        f"💸 Общие расходы: {format_amount(total_expense)} ₽\n"
        f"📊 Средний доход в месяц: {format_amount(avg_income)} ₽\n"
        f"🧾 Налог за всё время ({tax_rate}%): {format_amount(total_tax)} ₽",
        reply_markup=main_keyboard
    )

async def tax_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧾 О налогах:\n\n"
        "• 4% — с доходов от физлиц (самозанятый)\n"
        "• 6% — с доходов от юрлиц и ИП (самозанятый)\n"
        "• 13% — НДФЛ для ИП и физлиц\n\n"
        "Самозанятые:\n"
        "• Нет обязательных взносов\n"
        "• Лимит дохода: 2,4 млн ₽/год\n"
        "• Оплата до 25 числа следующего месяца\n\n"
        "Выбери свою ставку в «⚙️ Ставка налога».",
        reply_markup=main_keyboard
    )

async def set_tax_rate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Выбери налоговую ставку:",
        reply_markup=tax_rate_keyboard
    )

async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reset_pending"] = True
    await update.message.reply_text(
        "⚠️ Ты уверен, что хочешь удалить ВСЕ данные?\n\n"
        "Это действие нельзя отменить!\n\n"
        "Нажми «✅ Да, удалить» для подтверждения или любую другую кнопку для отмены.",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("✅ Да, удалить"), KeyboardButton("❌ Отмена")]
        ], resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "➕ Доход":
        context.user_data["mode"] = "income"
        await update.message.reply_text("Введи сумму дохода (только число):", reply_markup=cancel_keyboard)
        return
    
    if text == "➖ Расход":
        context.user_data["mode"] = "expense"
        await update.message.reply_text("Введи сумму расхода (только число):", reply_markup=cancel_keyboard)
        return
    
    if text == "📊 Баланс":
        await balance(update, context)
        return
    
    if text == "📊 Статистика":
        await stats(update, context)
        return
    
    if text == "🔄 Сброс":
        await reset_confirm(update, context)
        return
    
    if text == "↩️ Отменить":
        result = delete_last_transaction(user_id)
        if result:
            trans_type, amount, description, category = result
            await update.message.reply_text(
                f"↩️ Отменено: {'➕' if trans_type == 'income' else '➖'} {format_amount(amount)} ₽ ({category})",
                reply_markup=main_keyboard
            )
        else:
            await update.message.reply_text("Нечего отменять!", reply_markup=main_keyboard)
        return
    
    if text == "📥 Экспорт":
        report = export_report(user_id)
        await update.message.reply_text(report, reply_markup=main_keyboard)
        return
    
    if text == "⚙️ Ставка налога":
        await set_tax_rate_cmd(update, context)
        return
    
    if text == "4% (самозанятый, физлица)":
        set_tax_rate(user_id, 4.0)
        await update.message.reply_text("✅ Ставка налога изменена на 4%", reply_markup=main_keyboard)
        return
    
    if text == "6% (самозанятый, юрлица/ИП)":
        set_tax_rate(user_id, 6.0)
        await update.message.reply_text("✅ Ставка налога изменена на 6%", reply_markup=main_keyboard)
        return
    
    if text == "13% (НДФЛ)":
        set_tax_rate(user_id, 13.0)
        await update.message.reply_text("✅ Ставка налога изменена на 13%", reply_markup=main_keyboard)
        return
    
    if text == "✅ Да, удалить":
        if context.user_data.get("reset_pending"):
            reset_user_data(update.effective_user.id)
            context.user_data["reset_pending"] = False
            await update.message.reply_text("✅ Все данные удалены. Начинаем с чистого листа!", reply_markup=main_keyboard)
        else:
            await update.message.reply_text("Нечего удалять!", reply_markup=main_keyboard)
        return
    
    if text == "❌ Отмена":
        context.user_data.pop("mode", None)
        context.user_data.pop("reset_pending", None)
        context.user_data.pop("pending_amount", None)
        await update.message.reply_text("❌ Отменено.", reply_markup=main_keyboard)
        return
    
    if text == "🧾 О налогах":
        await tax_info(update, context)
        return
    
    if text == "ℹ️ Помощь":
        await help_cmd(update, context)
        return
    
    if text in ["🚕 Такси", "📱 Подписки", "🍔 Еда", "💼 Офис", "📢 Маркетинг", "📦 Прочее"]:
        pending_amount = context.user_data.get("pending_amount")
        if pending_amount:
            category_map = {
                "🚕 Такси": "Такси",
                "📱 Подписки": "Подписки",
                "🍔 Еда": "Еда",
                "💼 Офис": "Офис",
                "📢 Маркетинг": "Маркетинг",
                "📦 Прочее": "Прочее"
            }
            category = category_map[text]
            add_transaction(user_id, "expense", pending_amount, "Расход", category)
            await update.message.reply_text(
                f"✅ Записал расход: {format_amount(pending_amount)} ₽ ({category})",
                reply_markup=main_keyboard
            )
            context.user_data.pop("pending_amount", None)
        else:
            await update.message.reply_text("Сначала введи сумму расхода!", reply_markup=main_keyboard)
        return
    
    mode = context.user_data.get("mode")
    if mode:
        try:
            amount = float(text.replace(",", ".").replace(" ", ""))
            if amount <= 0:
                await update.message.reply_text("Сумма должна быть больше нуля!")
                return
            if amount > MAX_AMOUNT:
                await update.message.reply_text(f"Сумма не может быть больше {format_amount(MAX_AMOUNT)} ₽!")
                return
            
            if mode == "income":
                add_transaction(user_id, "income", amount, "Доход", "Работа")
                await update.message.reply_text(
                    f"✅ Записал доход: {format_amount(amount)} ₽",
                    reply_markup=main_keyboard
                )
                context.user_data["mode"] = None
            else:
                context.user_data["pending_amount"] = amount
                context.user_data["mode"] = None
                await update.message.reply_text(
                    f"Сумма: {format_amount(amount)} ₽. Выбери категорию расхода:",
                    reply_markup=category_keyboard
                )
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
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
