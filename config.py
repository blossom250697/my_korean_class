import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("BOT_TOKEN")
TUTOR_ID     = int(os.getenv("TUTOR_CHAT_ID", "0"))

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ── Настройки занятий ─────────────────────────────────────────────────────────
TRIAL_LESSON_PRICE_KRW          = 30_000
SINGLE_LESSON_PRICE_KRW         = 37_500
TWO_LESSONS_WEEKLY_MONTHLY_KRW  = 300_000
THREE_LESSONS_WEEKLY_MONTHLY_KRW= 450_000
LESSON_DURATION_MINUTES         = 180
LESSON_BUFFER_MINUTES           = 0   # перерыв между занятиями
MIN_BOOKING_DAYS_AHEAD          = 2   # минимум за сколько дней можно записаться
MAX_BOOKING_DAYS_AHEAD          = 31  # максимум дней вперёд

# ── Тексты ────────────────────────────────────────────────────────────────────
WELCOME_TEXT = {
    "ru": (
        "Здравствуйте! 🌿\n\n"
        "Добро пожаловать в бот для записи на индивидуальные занятия по корейскому языку.\n\n"
        "Здесь вы можете узнать о формате и стоимости занятий, оставить заявку "
        "на пробный урок или управлять своим расписанием.\n\n"
        "Выберите нужный раздел в меню ниже 👇"
    ),
    "en": (
        "Hello! 🌿\n\n"
        "Welcome to the booking bot for individual Korean language lessons.\n\n"
        "Here you can learn about the lesson format and pricing, apply for a trial lesson, "
        "or manage your schedule.\n\n"
        "Choose a section from the menu below 👇"
    ),
}

FORMAT_TEXT = {
    "ru": (
        "📚 <b>Формат занятий</b>\n\n"
        "На данный момент занятия проводятся только индивидуально — "
        "один преподаватель и один ученик.\n\n"
        "Такой формат позволяет подобрать программу под ваш уровень, цели и темп обучения, "
        "а также уделить больше времени разговорной практике и сложным темам.\n\n"
        f"Продолжительность одного занятия — 3 часа с перерывами.\n\n"
        "Групповые занятия на данный момент не предусмотрены."
    ),
    "en": (
        "📚 <b>Lesson Format</b>\n\n"
        "At the moment, lessons are held individually only — "
        "one teacher and one student.\n\n"
        "This format allows us to tailor the program to your level, goals and learning pace, "
        "and dedicate more time to speaking practice and challenging topics.\n\n"
        "Lesson duration — 3 hours with breaks.\n\n"
        "Group lessons are not available at this time."
    ),
}

PRICING_TEXT = {
    "ru": (
        "💳 <b>Стоимость занятий</b>\n\n"
        f"• 2 занятия в неделю — {TWO_LESSONS_WEEKLY_MONTHLY_KRW:,} вон в месяц\n"
        f"• 3 занятия в неделю — {THREE_LESSONS_WEEKLY_MONTHLY_KRW:,} вон в месяц\n"
        f"• Разовое занятие — {SINGLE_LESSON_PRICE_KRW:,} вон\n"
        f"• Пробное занятие — {TRIAL_LESSON_PRICE_KRW:,} вон\n\n"
        "Продолжительность одного занятия — 3 часа с перерывами."
    ).replace(",", " "),
    "en": (
        "💳 <b>Lesson Pricing</b>\n\n"
        f"• 2 lessons per week — {TWO_LESSONS_WEEKLY_MONTHLY_KRW:,} KRW/month\n"
        f"• 3 lessons per week — {THREE_LESSONS_WEEKLY_MONTHLY_KRW:,} KRW/month\n"
        f"• Single lesson — {SINGLE_LESSON_PRICE_KRW:,} KRW\n"
        f"• Trial lesson — {TRIAL_LESSON_PRICE_KRW:,} KRW\n\n"
        "Lesson duration — 3 hours with breaks."
    ).replace(",", " "),
}

PAYMENT_TERMS_TEXT = {
    "ru": (
        "📌 <b>Условия оплаты</b>\n\n"
        "Все занятия проводятся только по предварительной оплате.\n\n"
        "Выбранные дата и время окончательно закрепляются за учеником "
        "после подтверждения оплаты преподавателем.\n\n"
        "До подтверждения оплаты заявка не считается окончательной записью, "
        "а выбранное время может оставаться доступным для согласования.\n\n"
        "Бесплатные пробные занятия не проводятся."
    ),
    "en": (
        "📌 <b>Payment Terms</b>\n\n"
        "All lessons require prepayment.\n\n"
        "The selected date and time are confirmed only after the teacher "
        "verifies your payment.\n\n"
        "Until payment is confirmed, your booking is not final and "
        "the time slot may remain available.\n\n"
        "Free trial lessons are not offered."
    ),
}

TRIAL_INFO_TEXT = {
    "ru": (
        "🌱 <b>Пробное занятие</b>\n\n"
        "Пробное занятие проводится индивидуально и длится 3 часа с перерывами.\n\n"
        f"Стоимость — {TRIAL_LESSON_PRICE_KRW:,} вон.\n\n"
        "На занятии мы:\n"
        "• познакомимся;\n"
        "• определим ваш текущий уровень;\n"
        "• обсудим цели обучения;\n"
        "• разберём подходящий формат дальнейшей работы;\n"
        "• составим примерный план обучения.\n\n"
        "Пробное занятие проводится только по предварительной оплате.\n"
        "Дата и время закрепляются после подтверждения заявки и оплаты."
    ).replace(",", " "),
    "en": (
        "🌱 <b>Trial Lesson</b>\n\n"
        "The trial lesson is individual and lasts 3 hours with breaks.\n\n"
        f"Price — {TRIAL_LESSON_PRICE_KRW:,} KRW.\n\n"
        "During the lesson we will:\n"
        "• get acquainted;\n"
        "• assess your current level;\n"
        "• discuss your learning goals;\n"
        "• decide on the best study format;\n"
        "• outline a study plan.\n\n"
        "The trial lesson requires prepayment.\n"
        "Date and time are confirmed after your application and payment."
    ).replace(",", " "),
}

CONTACT_TEXT = {
    "ru": (
        "💬 <b>Связаться с преподавателем</b>\n\n"
        "Напишите ваш вопрос одним сообщением.\n"
        "Бот передаст его преподавателю вместе с вашим именем и Telegram-профилем."
    ),
    "en": (
        "💬 <b>Contact the Teacher</b>\n\n"
        "Write your question in one message.\n"
        "The bot will forward it to the teacher along with your name and Telegram profile."
    ),
}

# Тексты для бота (уведомления, подтверждения)
TEXTS = {
    "ru": {
        "start":          WELCOME_TEXT["ru"],
        "ask_name":       "Как вас зовут? (имя и фамилия)",
        "ask_level":      "Укажите ваш уровень корейского:\n\nНапример: Начинающий, Elementary, TOPIK 1, A2…",
        "ask_frequency":  "Сколько раз в неделю хотите заниматься?",
        "ask_time":       "В какое время вам удобно заниматься? (укажите несколько вариантов)",
        "ask_message":    "Есть ли дополнительные пожелания? (или напишите «нет»)",
        "applied":        "✅ Заявка отправлена! Преподаватель свяжется с вами в ближайшее время.",
        "approved":       "🎉 Ваша заявка одобрена!\n\nДобро пожаловать на занятия по корейскому!\nПреподаватель свяжется с вами для уточнения деталей.",
        "rejected":       "😔 К сожалению, в данный момент нет свободных мест.\n\nМы сохраним вашу заявку и свяжемся, как только появится место.",
        "reminder_lesson": "📚 Напоминание!\n\n{title} по корейскому.\n📅 {date}\n⏰ {time}\n\nДо встречи! 화이팅! 💪",
        "reminder_payment":"💳 Напоминание об оплате\n\nУ вас есть задолженность: {amount} ₩\n\nПожалуйста, оплатите при возможности. Спасибо!",
        "freq_2x":        "2 раза в неделю",
        "freq_3x":        "3 раза в неделю",
        "lesson_confirmed":"🎉 Занятие подтверждено!\n\n📅 {date}\n⏰ {time}\n\nДо встречи! 화이팅! 💪",
    },
    "en": {
        "start":          WELCOME_TEXT["en"],
        "ask_name":       "What is your name? (first and last name)",
        "ask_level":      "What is your Korean level?\n\nE.g.: Beginner, Elementary, TOPIK 1, A2…",
        "ask_frequency":  "How many times per week would you like to study?",
        "ask_time":       "What time is convenient for you? (list several options)",
        "ask_message":    "Any additional wishes? (or write «no»)",
        "applied":        "✅ Application sent! The teacher will contact you soon.",
        "approved":       "🎉 Your application has been approved!\n\nWelcome to Korean lessons!\nThe teacher will contact you to confirm the details.",
        "rejected":       "😔 Unfortunately, there are no available spots right now.\n\nWe'll keep your application and contact you when a spot opens up.",
        "reminder_lesson": "📚 Reminder!\n\n{title}.\n📅 {date}\n⏰ {time}\n\nSee you! 화이팅! 💪",
        "reminder_payment":"💳 Payment reminder\n\nOutstanding balance: {amount} ₩\n\nPlease pay when you can. Thank you!",
        "freq_2x":        "2 times a week",
        "freq_3x":        "3 times a week",
        "lesson_confirmed":"🎉 Lesson confirmed!\n\n📅 {date}\n⏰ {time}\n\nSee you! 화이팅! 💪",
    },
}
