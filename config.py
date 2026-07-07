import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN")
TUTOR_ID     = int(os.getenv("TUTOR_CHAT_ID", "0"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ── Тексты для учеников ───────────────────────────────────────────────────────
TEXTS = {
    "ru": {
        "start": (
            "👋 Привет! Это бот репетитора корейского языка.\n\n"
            "Здесь вы можете:\n"
            "📝 /apply — подать заявку на занятия\n"
            "📅 /schedule — узнать расписание\n"
            "💳 /payment — статус оплаты\n"
            "❓ /help — помощь"
        ),
        "ask_name":      "Как вас зовут? (имя и фамилия)",
        "ask_level":     "Укажите ваш уровень корейского:\n\nНапример: Начинающий, Elementary, TOPIK 1, A2…",
        "ask_frequency": "Сколько раз в неделю хотите заниматься?",
        "ask_time":      "В какое время вам удобно заниматься? (укажите несколько вариантов)",
        "ask_message":   "Есть ли дополнительные пожелания? (или напишите «нет»)",
        "applied":       "✅ Заявка отправлена! Преподаватель свяжется с вами в ближайшее время.",
        "reminder_lesson": (
            "📚 Напоминание!\n\n"
            "Завтра у вас занятие по корейскому.\n"
            "📅 Дата: {date}\n\n"
            "До встречи! 화이팅! 💪"
        ),
        "reminder_payment": (
            "💳 Напоминание об оплате\n\n"
            "У вас есть задолженность за обучение.\n"
            "Сумма: {amount} ₩\n\n"
            "Пожалуйста, оплатите при возможности. Спасибо!"
        ),
        "approved": (
            "🎉 Ваша заявка одобрена!\n\n"
            "Добро пожаловать на занятия по корейскому!\n"
            "Преподаватель скоро свяжется с вами для уточнения деталей."
        ),
        "rejected": (
            "😔 К сожалению, в данный момент нет свободных мест.\n\n"
            "Мы сохраним вашу заявку и свяжемся, как только появится место."
        ),
        "freq_2x": "2 раза в неделю",
        "freq_3x": "3 раза в неделю",
    },
    "en": {
        "start": (
            "👋 Hello! This is a Korean language tutor bot.\n\n"
            "You can:\n"
            "📝 /apply — apply for lessons\n"
            "📅 /schedule — check your schedule\n"
            "💳 /payment — payment status\n"
            "❓ /help — help"
        ),
        "ask_name":      "What is your name? (first and last name)",
        "ask_level":     "What is your Korean level?\n\nE.g.: Beginner, Elementary, TOPIK 1, A2…",
        "ask_frequency": "How many times per week would you like to study?",
        "ask_time":      "What time is convenient for you? (list several options)",
        "ask_message":   "Any additional wishes? (or write «no»)",
        "applied":       "✅ Application sent! The teacher will contact you soon.",
        "reminder_lesson": (
            "📚 Reminder!\n\n"
            "You have a Korean lesson tomorrow.\n"
            "📅 Date: {date}\n\n"
            "See you soon! 화이팅! 💪"
        ),
        "reminder_payment": (
            "💳 Payment reminder\n\n"
            "You have an outstanding balance.\n"
            "Amount: {amount} ₩\n\n"
            "Please pay when you can. Thank you!"
        ),
        "approved": (
            "🎉 Your application has been approved!\n\n"
            "Welcome to Korean lessons!\n"
            "The teacher will contact you soon to confirm the details."
        ),
        "rejected": (
            "😔 Unfortunately, there are no available spots right now.\n\n"
            "We'll keep your application and contact you when a spot opens up."
        ),
        "freq_2x": "2 times a week",
        "freq_3x": "3 times a week",
    },
}
