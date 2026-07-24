import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8381828847:AAFaWP-IXVvdVJSpEac1hciXRWOAidHTHT0"

MAX_AMOUNT = 10_000_000
SELF_EMPLOYED_LIMIT = 2_400_000
SERVER_TZ = "UTC-7"

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
            tax_rate REAL DEFAULT 6.0,
            goal REAL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            rating INTEGER,
            text TEXT,
            date TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promos (
            code TEXT PRIMARY KEY,
            description TEXT DEFAULT '',
            max_uses INTEGER DEFAULT 1,
            used INTEGER DEFAULT 0
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

def get_goal(user_id):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT goal FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def set_goal(user_id, goal):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, tax_rate, goal) VALUES (?, (SELECT tax_rate FROM users WHERE user_id = ?), ?)", (user_id, user_id, goal))
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

def add_review(user_id, rating, text):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reviews WHERE user_id = ?", (user_id,))
    cursor.execute("INSERT INTO reviews (user_id, rating, text, date) VALUES (?, ?, ?, ?)",
                   (user_id, rating, text, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_reviews(rating_filter=0, offset=0, limit=5):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    if rating_filter > 0:
        cursor.execute("SELECT rating, text, date FROM reviews WHERE rating = ? ORDER BY id DESC LIMIT ? OFFSET ?", (rating_filter, limit, offset))
        cursor.execute("SELECT AVG(rating), COUNT(*) FROM reviews WHERE rating = ?", (rating_filter,))
    else:
        cursor.execute("SELECT rating, text, date FROM reviews ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        cursor.execute("SELECT AVG(rating), COUNT(*) FROM reviews")
    
    rows = cursor.fetchall()
    avg, count = cursor.fetchone()
    conn.close()
    return rows, round(avg, 1) if avg else 0, count

def has_more_reviews(rating_filter=0, offset=0, limit=5):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    if rating_filter > 0:
        cursor.execute("SELECT COUNT(*) FROM reviews WHERE rating = ?", (rating_filter,))
    else:
        cursor.execute("SELECT COUNT(*) FROM reviews")
    total = cursor.fetchone()[0]
    conn.close()
    return total > offset + limit

def check_promo(code):
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT max_uses, used FROM promos WHERE code = ?", (code,))
    row = cursor.fetchone()
    if row:
        max_uses, used = row
        if used < max_uses:
            cursor.execute("UPDATE promos SET used = used + 1 WHERE code = ?", (code,))
            conn.commit()
            conn.close()
            return True
    conn.close()
    return False

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

def get_month_income(user_id):
    month_start = f"{datetime.now().strftime('%Y-%m')}-01"
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE user_id = ? AND type = 'income' AND date >= ?", (user_id, month_start))
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
    report += f"Ставка налога: {tax_rate}%\n"
    report += f"🕐 Время сервера ({SERVER_TZ})\n\n"
    report += f"💰 Всего доходов: {format_amount(income)} ₽\n"
    report += f"💸 Всего расходов: {format_amount(expense)} ₽\n"
    report += f"🧾 Налог к уплате: {format_amount(tax)} ₽\n"
    report += f"✅ Чистый остаток: {format_amount(net)} ₽\n"
    
    if limit_left is not None:
        if limit_left >= 0:
            report += f"\n📊 До лимита (2,4 млн): {format_amount(limit_left)} ₽\n"
        else:
            report += f"\n⚠️ Лимит превышен на {format_amount(abs(limit_left))} ₽!\n"
    
    report += "\n━━━━━━━━━━━━━━━━\n📋 ПОСЛЕДНИЕ ОПЕРАЦИИ:\n\n"
    
    for row in rows:
        trans_type, amount, description, category, date = row
        emoji = "➕" if trans_type == "income" else "➖"
        report += f"{emoji} {format_amount(amount)} ₽ | {category} | {description} | {date}\n"
    
    return report

main_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("➕ Доход"), KeyboardButton("➖ Расход")],
    [KeyboardButton("📊 Баланс"), KeyboardButton("📊 Статистика")],
    [KeyboardButton("📥 Экспорт"), KeyboardButton("🔔 Ещё")]
], resize_keyboard=True)

more_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🎯 Цель"), KeyboardButton("⚙️ Ставка налога")],
    [KeyboardButton("🧾 О налогах"), KeyboardButton("⭐ Отзывы")],
    [KeyboardButton("🎟️ Промокод"), KeyboardButton("↩️ Отменить")],
    [KeyboardButton("🔄 Сброс"), KeyboardButton("⬅️ Назад")]
], resize_keyboard=True)

review_menu_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("📝 Оставить отзыв"), KeyboardButton("📖 Посмотреть отзывы")],
    [KeyboardButton("⬅️ Назад")]
], resize_keyboard=True)

review_filter_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("⭐5"), KeyboardButton("⭐4"), KeyboardButton("⭐3")],
    [KeyboardButton("⭐2"), KeyboardButton("⭐1"), KeyboardButton("🌟 Все")],
    [KeyboardButton("⬅️ Назад")]
], resize_keyboard=True)

category_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("🚕 Такси"), KeyboardButton("📱 Подписки")],
    [KeyboardButton("🍔 Еда"), KeyboardButton("💼 Офис")],
    [KeyboardButton("📢 Маркетинг"), KeyboardButton("📦 Прочее")],
    [KeyboardButton("⬅️ Назад")]
], resize_keyboard=True)

cancel_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("⬅️ Назад")]
], resize_keyboard=True)

tax_rate_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("4% (самозанятый, физлица)")],
    [KeyboardButton("6% (самозанятый, юрлица/ИП)")],
    [KeyboardButton("13% (НДФЛ)")],
    [KeyboardButton("⬅️ Назад")]
], resize_keyboard=True)

review_rate_keyboard = ReplyKeyboardMarkup([
    [KeyboardButton("⭐1"), KeyboardButton("⭐2"), KeyboardButton("⭐3")],
    [KeyboardButton("⭐4"), KeyboardButton("⭐5")],
    [KeyboardButton("⬅️ Назад")]
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
        "• «📥 Экспорт» — скачать отчёт\n"
        "• «🔔 Ещё» — дополнительные функции\n\n"
        "Скоро я научусь понимать твои сообщения и чеки!",
        reply_markup=main_keyboard
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    income, expense, tax, net, tax_rate = get_balance(user_id)
    year_income = get_year_income(user_id)
    month_income = get_month_income(user_id)
    goal = get_goal(user_id)
    
    warning = ""
    if net < 0:
        warning += f"\n\n⚠️ Твои расходы ({format_amount(expense)} ₽) превышают чистый доход. Ты в минусе на {format_amount(abs(net))} ₽."
    
    limit_info = ""
    if tax_rate in [4.0, 6.0]:
        limit_left = SELF_EMPLOYED_LIMIT - year_income
        percent = round((year_income / SELF_EMPLOYED_LIMIT) * 100, 1)
        if limit_left >= 0:
            limit_info = f"\n\n📊 Лимит самозанятого:\nИспользовано: {format_amount(year_income)} ₽ ({percent}%)\nОсталось: {format_amount(limit_left)} ₽"
        else:
            limit_info = f"\n\n📊 Лимит самозанятого:\nИспользовано: {format_amount(year_income)} ₽ ({percent}%)\n⚠️ Лимит превышен на {format_amount(abs(limit_left))} ₽!"
    
    goal_info = ""
    if goal > 0:
        percent = round((month_income / goal) * 100, 1) if goal > 0 else 0
        left = goal - month_income
        bar_len = min(int(percent / 10), 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        if left > 0:
            goal_info = f"\n\n🎯 Цель на месяц: {format_amount(goal)} ₽\nПрогресс: [{bar}] {percent}%\nОсталось: {format_amount(left)} ₽"
        else:
            goal_info = f"\n\n🎯 Цель на месяц: {format_amount(goal)} ₽\nПрогресс: [{bar}] {percent}%\n✅ Цель достигнута!"
    
    await update.message.reply_text(
        f"📊 Твой баланс:\n\n"
        f"💰 Доходы: {format_amount(income)} ₽\n"
        f"💸 Расходы: {format_amount(expense)} ₽\n"
        f"🧾 Налог к уплате ({tax_rate}%): {format_amount(tax)} ₽\n\n"
        f"✅ Чистый остаток: {format_amount(net)} ₽"
        f"{limit_info}"
        f"{goal_info}"
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
        f"📊 Статистика:\n"
        f"🕐 Время сервера ({SERVER_TZ})\n\n"
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
    now = datetime.now()
    if now.day <= 25:
        deadline_month = now.month - 1 if now.month > 1 else 12
        deadline_date = f"25.{now.month:02d}.{now.year}"
        tax_for = f"{deadline_month:02d}.{now.year}"
    else:
        deadline_date = f"25.{now.month + 1:02d}.{now.year}" if now.month < 12 else f"25.01.{now.year + 1}"
        tax_for = f"{now.month:02d}.{now.year}"
    
    await update.message.reply_text(
        "🧾 О налогах:\n\n"
        "• 4% — с доходов от физлиц (самозанятый)\n"
        "• 6% — с доходов от юрлиц и ИП (самозанятый)\n"
        "• 13% — НДФЛ для ИП и физлиц\n\n"
        "Самозанятые:\n"
        "• Нет обязательных взносов\n"
        "• Лимит дохода: 2,4 млн ₽/год\n"
        "• Оплата до 25 числа следующего месяца\n\n"
        f"📅 Ближайший дедлайн: {deadline_date}\n"
        f"📌 Налог за {tax_for}\n\n"
        "Выбери свою ставку в «⚙️ Ставка налога».",
        reply_markup=main_keyboard
    )

async def set_tax_rate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери налоговую ставку:", reply_markup=tax_rate_keyboard)

async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reset_pending"] = True
    await update.message.reply_text(
        "⚠️ Ты уверен, что хочешь удалить ВСЕ данные?\n\n"
        "Это действие нельзя отменить!\n\n"
        "Нажми «✅ Да, удалить» для подтверждения или любую другую кнопку для отмены.",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("✅ Да, удалить"), KeyboardButton("⬅️ Назад")]
        ], resize_keyboard=True)
    )

async def feedback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⭐ Отзывы:", reply_markup=review_menu_keyboard)

async def feedback_write(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("taxbuddy.db")
    cursor = conn.cursor()
    cursor.execute("SELECT rating, text FROM reviews WHERE user_id = ?", (user_id,))
    existing = cursor.fetchone()
    conn.close()
    
    if existing:
        await update.message.reply_text(
            f"У тебя уже есть отзыв ({existing[0]}⭐). Если продолжишь, он обновится.\n\n"
            f"Твой отзыв: «{existing[1]}»\n\n"
            "Поставь новую оценку (1-5):",
            reply_markup=review_rate_keyboard
        )
    else:
        context.user_data["feedback_pending"] = True
        await update.message.reply_text("⭐ Поставь оценку боту (1-5):", reply_markup=review_rate_keyboard)

async def feedback_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["review_offset"] = 0
    context.user_data["review_filter"] = 0
    
    reviews, avg, count = get_reviews()
    if count == 0:
        await update.message.reply_text("⭐ Пока нет отзывов. Будь первым!", reply_markup=review_menu_keyboard)
        return
    
    text = f"⭐ Средняя оценка: {avg}/5 (всего {count})\n\n"
    text += "Выбери фильтр:"
    await update.message.reply_text(text, reply_markup=review_filter_keyboard)

async def show_filtered_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE, rating_filter, offset):
    reviews, avg, count = get_reviews(rating_filter, offset)
    
    if not reviews:
        await update.message.reply_text("Нет отзывов с таким фильтром.", reply_markup=review_filter_keyboard)
        return
    
    filter_text = f"⭐{rating_filter}" if rating_filter > 0 else "🌟 Все"
    text = f"Отзывы ({filter_text}):\n\n"
    
    for rating, review_text, date in reviews:
        stars = "⭐" * rating
        text += f"{stars}\n{review_text}\n📅 {date}\n\n"
    
    more = has_more_reviews(rating_filter, offset)
    if more:
        text += "Показать ещё 5 отзывов?"
        await update.message.reply_text(
            text,
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("▶️ Да, ещё"), KeyboardButton("⬅️ Назад к фильтрам")]
            ], resize_keyboard=True)
        )
    else:
        text += "Это все отзывы."
        await update.message.reply_text(text, reply_markup=review_filter_keyboard)

async def goal_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["goal_pending"] = True
    await update.message.reply_text("🎯 Введи цель по доходу на месяц (только число):", reply_markup=cancel_keyboard)

async def promo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["promo_pending"] = True
    await update.message.reply_text("🎟️ Введи промокод:", reply_markup=cancel_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "🔔 Ещё":
        await update.message.reply_text("Дополнительные функции:", reply_markup=more_keyboard)
        return
    
    if text == "⬅️ Назад":
        context.user_data.pop("mode", None)
        context.user_data.pop("reset_pending", None)
        context.user_data.pop("pending_amount", None)
        context.user_data.pop("feedback_pending", None)
        context.user_data.pop("goal_pending", None)
        context.user_data.pop("promo_pending", None)
        context.user_data.pop("feedback_rating", None)
        context.user_data.pop("review_offset", None)
        context.user_data.pop("review_filter", None)
        await update.message.reply_text("Главное меню.", reply_markup=main_keyboard)
        return
    
    if text == "⬅️ Назад к фильтрам":
        await feedback_view(update, context)
        return
    
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
    
    if text == "⭐ Отзывы":
        await feedback_menu(update, context)
        return
    
    if text == "📝 Оставить отзыв":
        await feedback_write(update, context)
        return
    
    if text == "📖 Посмотреть отзывы":
        await feedback_view(update, context)
        return
    
    if text in ["⭐5", "⭐4", "⭐3", "⭐2", "⭐1"]:
        rating = int(text[1])
        context.user_data["review_filter"] = rating
        context.user_data["review_offset"] = 0
        await show_filtered_reviews(update, context, rating, 0)
        return
    
    if text == "🌟 Все":
        context.user_data["review_filter"] = 0
        context.user_data["review_offset"] = 0
        await show_filtered_reviews(update, context, 0, 0)
        return
    
    if text == "▶️ Да, ещё":
        rating_filter = context.user_data.get("review_filter", 0)
        offset = context.user_data.get("review_offset", 0) + 5
        context.user_data["review_offset"] = offset
        await show_filtered_reviews(update, context, rating_filter, offset)
        return
    
    if text == "🎯 Цель":
        await goal_set(update, context)
        return
    
    if text == "🎟️ Промокод":
        await promo_cmd(update, context)
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
    
    if text in ["⭐1", "⭐2", "⭐3", "⭐4", "⭐5"]:
        rating = int(text[1])
        context.user_data["feedback_rating"] = rating
        await update.message.reply_text(f"Поставил {rating} ⭐. Теперь напиши отзыв:", reply_markup=cancel_keyboard)
        return
    
    if "feedback_rating" in context.user_data:
        rating = context.user_data.pop("feedback_rating")
        add_review(user_id, rating, text)
        await update.message.reply_text(f"⭐ Спасибо за отзыв! Ты поставил {rating}/5.", reply_markup=main_keyboard)
        return
    
    if context.user_data.get("goal_pending"):
        try:
            goal = float(text.replace(",", ".").replace(" ", ""))
            if goal <= 0:
                await update.message.reply_text("Сумма должна быть больше нуля!")
                return
            set_goal(user_id, goal)
            context.user_data["goal_pending"] = False
            await update.message.reply_text(f"🎯 Цель на месяц: {format_amount(goal)} ₽. Удачи!", reply_markup=main_keyboard)
        except ValueError:
            await update.message.reply_text("Введи только число! Например: 100000")
        return
    
    if context.user_data.get("promo_pending"):
        code = text.strip().upper()
        if check_promo(code):
            await update.message.reply_text("🎟️ Промокод активирован! Premium-доступ получен.", reply_markup=main_keyboard)
        else:
            await update.message.reply_text("❌ Промокод недействителен или уже использован.", reply_markup=main_keyboard)
        context.user_data["promo_pending"] = False
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
    app.add_handler(CommandHandler("feedback", feedback_menu))
    app.add_handler(CommandHandler("reviews", feedback_view))
    app.add_handler(CommandHandler("promo", promo_cmd))
    app.add_handler(CommandHandler("goal", goal_set))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
