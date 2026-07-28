"""
Korean Tutor Bot — v3
Этап 1: новое меню, одиночное подтверждение, запись с проверкой окон
"""
import asyncio
import logging
import uuid
import zoneinfo
from datetime import datetime, date, timedelta
import calendar as cal

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    BOT_TOKEN, TUTOR_ID, TEXTS,
    WELCOME_TEXT, FORMAT_TEXT, PRICING_TEXT,
    PAYMENT_TERMS_TEXT, TRIAL_INFO_TEXT, CONTACT_TEXT,
    LESSON_DURATION_MINUTES, LESSON_BUFFER_MINUTES,
    MIN_BOOKING_DAYS_AHEAD, MAX_BOOKING_DAYS_AHEAD,
)
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

SEOUL = zoneinfo.ZoneInfo("Asia/Seoul")

# ── Вспомогательные функции дат ───────────────────────────────────────────────

def today_seoul() -> date:
    return datetime.now(SEOUL).date()

def min_booking_date() -> date:
    return today_seoul() + timedelta(days=MIN_BOOKING_DAYS_AHEAD)

def max_booking_date() -> date:
    t = today_seoul()
    # +1 месяц
    m = t.month + 1
    y = t.year + (1 if m > 12 else 0)
    m = m if m <= 12 else m - 12
    last = cal.monthrange(y, m)[1]
    d = min(t.day, last)
    return date(y, m, d)

def time_to_min(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m

def min_to_time(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"

def fmt_date(d: date) -> str:
    months = ["января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]
    return f"{d.day} {months[d.month-1]}"

# ── FSM ───────────────────────────────────────────────────────────────────────

class ApplyForm(StatesGroup):
    lang     = State()
    name     = State()
    level    = State()
    frequency= State()
    wishes   = State()
    username = State()
    message  = State()

class BookLesson(StatesGroup):
    """Запись на разовое занятие существующим учеником"""
    date_select = State()
    time_select = State()
    confirm     = State()

class ContactTeacher(StatesGroup):
    waiting_message = State()

class ScheduleSetup(StatesGroup):
    select_app = State()
    frequency  = State()
    days       = State()
    day_times  = State()
    has_free   = State()
    confirm    = State()

class RemindForm(StatesGroup):
    type_select    = State()
    student_select = State()

# ── Клавиатуры ────────────────────────────────────────────────────────────────

DAYS_RU = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
DAYS_EN = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def tutor_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Заявки"),     KeyboardButton(text="👥 Ученики")],
        [KeyboardButton(text="📅 Расписание"), KeyboardButton(text="💸 Должники")],
        [KeyboardButton(text="📣 Рассылка"),   KeyboardButton(text="❓ Помощь")],
    ], resize_keyboard=True, persistent=True)

def student_kb(lang: str, has_pending: bool = False, has_upcoming: bool = False) -> ReplyKeyboardMarkup:
    if lang == "ru":
        rows = [
            [KeyboardButton(text="📅 Моё следующее занятие"), KeyboardButton(text="🗓 Записаться на занятие")],
            [KeyboardButton(text="📚 Формат занятий"),        KeyboardButton(text="💳 Стоимость и оплата")],
            [KeyboardButton(text="💬 Связаться с преподавателем")],
        ]
        if has_pending:
            rows.append([KeyboardButton(text="🚫 Отозвать заявку")])
    else:
        rows = [
            [KeyboardButton(text="📅 My next lesson"),    KeyboardButton(text="🗓 Book a lesson")],
            [KeyboardButton(text="📚 Lesson format"),     KeyboardButton(text="💳 Pricing & payment")],
            [KeyboardButton(text="💬 Contact teacher")],
        ]
        if has_pending:
            rows.append([KeyboardButton(text="🚫 Cancel application")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, persistent=True)

def new_user_kb(lang: str) -> ReplyKeyboardMarkup:
    if lang == "ru":
        rows = [
            [KeyboardButton(text="🌱 Записаться на пробное занятие")],
            [KeyboardButton(text="📚 Формат занятий"), KeyboardButton(text="💳 Стоимость занятий")],
            [KeyboardButton(text="📌 Условия оплаты"), KeyboardButton(text="💬 Связаться с преподавателем")],
        ]
    else:
        rows = [
            [KeyboardButton(text="🌱 Apply for a trial lesson")],
            [KeyboardButton(text="📚 Lesson format"), KeyboardButton(text="💳 Pricing")],
            [KeyboardButton(text="📌 Payment terms"), KeyboardButton(text="💬 Contact teacher")],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, persistent=True)

def days_kb(selected: list) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, day in enumerate(DAYS_RU):
        check = "✅ " if i in selected else ""
        row.append(InlineKeyboardButton(text=f"{check}{day}", callback_data=f"tday_{i}"))
        if len(row) == 4:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✓ Готово", callback_data="tdays_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ── Проверка окон ─────────────────────────────────────────────────────────────

def get_free_slots(target_date: date, work_start: str = "10:00", work_end: str = "19:00") -> list[str]:
    """
    Возвращает список свободных окон для записи на target_date.
    Учитывает: занятия учеников (таблица sessions) + длительность урока.
    """
    try:
        booked = db.get_sessions_for_date(target_date.isoformat())
    except Exception:
        booked = []

    duration = LESSON_DURATION_MINUTES
    buffer   = LESSON_BUFFER_MINUTES
    ws = time_to_min(work_start)
    we = time_to_min(work_end)

    # Список занятых отрезков с буфером
    busy = []
    for s in booked:
        if s.get("time"):
            start = time_to_min(s["time"])
            end   = start + duration + buffer
            busy.append((start, end))
    busy.sort()

    # Генерируем кандидатов каждые 30 минут
    slots = []
    t = ws
    while t + duration <= we:
        t_end = t + duration
        # Проверяем пересечение
        conflict = False
        for (bs, be) in busy:
            if t < be and t_end > bs:
                conflict = True
                break
        if not conflict:
            slots.append(min_to_time(t))
        t += 30

    return slots

def get_available_dates(days_count: int = 31) -> list[tuple]:
    """Возвращает список (date, free_slots) для дат от min до max"""
    result = []
    d = min_booking_date()
    max_d = max_booking_date()
    while d <= max_d:
        slots = get_free_slots(d)
        if slots:
            result.append((d, slots))
        d += timedelta(days=1)
    return result

def find_next_available(from_date: date) -> tuple | None:
    """Ищет ближайшую дату со свободными окнами"""
    d = from_date + timedelta(days=1)
    max_d = max_booking_date()
    while d <= max_d:
        slots = get_free_slots(d)
        if slots:
            return (d, slots)
        d += timedelta(days=1)
    return None

# ── Вспомогательные ───────────────────────────────────────────────────────────

def get_lang(user) -> str:
    lc = user.language_code or "ru"
    return "en" if not lc.startswith("ru") else "ru"

def t(lang: str, key: str, **kwargs) -> str:
    text = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    return text.format(**kwargs) if kwargs else text

def get_reminder_title(day_diff: int, lang: str) -> str | None:
    def pluralize(n):
        m10, m100 = n % 10, n % 100
        if m10 == 1 and m100 != 11: return "день"
        if 2 <= m10 <= 4 and not (12 <= m100 <= 14): return "дня"
        return "дней"

    if day_diff < 0: return None
    if lang == "ru":
        if day_diff == 0: return "Сегодня у вас занятие"
        if day_diff == 1: return "Завтра у вас занятие"
        if day_diff == 2: return "Через два дня у вас занятие"
        return f"У вас занятие через {day_diff} {pluralize(day_diff)}"
    else:
        if day_diff == 0: return "You have a lesson today"
        if day_diff == 1: return "You have a lesson tomorrow"
        if day_diff == 2: return "You have a lesson in two days"
        return f"You have a lesson in {day_diff} days"

def get_day_diff(lesson_date_str: str) -> int:
    today = today_seoul()
    ld = date.fromisoformat(lesson_date_str[:10])
    return (ld - today).days

# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    # Не сбрасываем FSM если есть активное состояние — только если это явный /start
    await state.clear()

    if msg.from_user.id == TUTOR_ID:
        await msg.answer("👩‍🏫 Панель преподавателя", reply_markup=tutor_kb())
        return

    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)

    if student:
        lang = student.get("telegram_lang", lang)
        pending = db.get_pending_application(msg.from_user.id)
        await msg.answer(
            WELCOME_TEXT[lang],
            reply_markup=student_kb(lang, has_pending=bool(pending))
        )
    else:
        await msg.answer(WELCOME_TEXT[lang], reply_markup=new_user_kb(lang))

# ── Информационные разделы ────────────────────────────────────────────────────

def info_kb(lang: str, buttons: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=b[0], callback_data=b[1])] for b in buttons]
    rows.append([InlineKeyboardButton(
        text="⬅️ Главное меню" if lang=="ru" else "⬅️ Main menu",
        callback_data="go_main_menu"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "go_main_menu")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_lang(cb.from_user)
    student = db.get_student_by_telegram(cb.from_user.id)
    if student:
        lang = student.get("telegram_lang", lang)
        pending = db.get_pending_application(cb.from_user.id)
        await cb.message.answer(WELCOME_TEXT[lang], reply_markup=student_kb(lang, has_pending=bool(pending)))
    else:
        await cb.message.answer(WELCOME_TEXT[lang], reply_markup=new_user_kb(lang))
    await cb.answer()

@dp.message(F.text.in_({"📚 Формат занятий", "📚 Lesson format"}))
async def show_format(msg: Message):
    lang = "ru" if "Формат" in msg.text else "en"
    kb = info_kb(lang, [
        ["💳 Посмотреть стоимость" if lang=="ru" else "💳 View pricing", "show_pricing"],
        ["🌱 Записаться на пробное занятие" if lang=="ru" else "🌱 Apply for trial", "show_trial"],
    ])
    await msg.answer(FORMAT_TEXT[lang], parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.in_({"💳 Стоимость занятий", "💳 Стоимость и оплата", "💳 Pricing", "💳 Pricing & payment"}))
async def show_pricing(msg: Message):
    lang = "ru" if any(r in msg.text for r in ["Стоимость", "Оплата"]) else "en"
    kb = info_kb(lang, [
        ["📌 Условия оплаты" if lang=="ru" else "📌 Payment terms", "show_payment_terms"],
        ["📚 Формат занятий" if lang=="ru" else "📚 Lesson format", "show_format_cb"],
        ["🌱 Записаться на пробное занятие" if lang=="ru" else "🌱 Apply for trial", "show_trial"],
    ])
    await msg.answer(PRICING_TEXT[lang], parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.in_({"📌 Условия оплаты", "📌 Payment terms"}))
async def show_payment_terms(msg: Message):
    lang = "ru" if "Условия" in msg.text else "en"
    kb = info_kb(lang, [
        ["💳 Посмотреть стоимость" if lang=="ru" else "💳 View pricing", "show_pricing"],
        ["🌱 Записаться на пробное занятие" if lang=="ru" else "🌱 Apply for trial", "show_trial"],
    ])
    await msg.answer(PAYMENT_TERMS_TEXT[lang], parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.in_({"🌱 Записаться на пробное занятие", "🌱 Apply for a trial lesson"}))
async def show_trial(msg: Message):
    lang = "ru" if "пробное" in msg.text.lower() else "en"
    kb = info_kb(lang, [
        ["📝 Оставить заявку" if lang=="ru" else "📝 Apply now", "start_apply"],
        ["💳 Стоимость занятий" if lang=="ru" else "💳 Pricing", "show_pricing"],
    ])
    await msg.answer(TRIAL_INFO_TEXT[lang], parse_mode="HTML", reply_markup=kb)

# Callbacks для информационных разделов
@dp.callback_query(F.data == "show_pricing")
async def cb_pricing(cb: CallbackQuery):
    lang = get_lang(cb.from_user)
    kb = info_kb(lang, [
        ["📌 Условия оплаты" if lang=="ru" else "📌 Payment terms", "show_payment_terms"],
        ["🌱 Записаться на пробное занятие" if lang=="ru" else "🌱 Apply for trial", "show_trial"],
    ])
    await cb.message.edit_text(PRICING_TEXT[lang], parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data == "show_payment_terms")
async def cb_payment_terms(cb: CallbackQuery):
    lang = get_lang(cb.from_user)
    kb = info_kb(lang, [
        ["💳 Посмотреть стоимость" if lang=="ru" else "💳 View pricing", "show_pricing"],
        ["🌱 Записаться на пробное занятие" if lang=="ru" else "🌱 Apply for trial", "show_trial"],
    ])
    await cb.message.edit_text(PAYMENT_TERMS_TEXT[lang], parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data == "show_trial")
async def cb_trial(cb: CallbackQuery):
    lang = get_lang(cb.from_user)
    kb = info_kb(lang, [
        ["📝 Оставить заявку" if lang=="ru" else "📝 Apply now", "start_apply"],
        ["💳 Стоимость занятий" if lang=="ru" else "💳 Pricing", "show_pricing"],
    ])
    await cb.message.edit_text(TRIAL_INFO_TEXT[lang], parse_mode="HTML", reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data == "show_format_cb")
async def cb_format(cb: CallbackQuery):
    lang = get_lang(cb.from_user)
    kb = info_kb(lang, [
        ["💳 Посмотреть стоимость" if lang=="ru" else "💳 View pricing", "show_pricing"],
        ["🌱 Записаться на пробное занятие" if lang=="ru" else "🌱 Apply for trial", "show_trial"],
    ])
    await cb.message.edit_text(FORMAT_TEXT[lang], parse_mode="HTML", reply_markup=kb)
    await cb.answer()

# ── Связь с преподавателем ────────────────────────────────────────────────────

@dp.message(F.text.in_({"💬 Связаться с преподавателем", "💬 Contact teacher"}))
async def show_contact(msg: Message, state: FSMContext):
    lang = "ru" if "Связаться" in msg.text else "en"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✍️ Написать сообщение" if lang=="ru" else "✍️ Write a message",
            callback_data="write_to_teacher"
        )],
        [InlineKeyboardButton(
            text="⬅️ Главное меню" if lang=="ru" else "⬅️ Main menu",
            callback_data="go_main_menu"
        )],
    ])
    await msg.answer(CONTACT_TEXT[lang], parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "write_to_teacher")
async def cb_write_teacher(cb: CallbackQuery, state: FSMContext):
    lang = get_lang(cb.from_user)
    text = "✍️ Напишите ваш вопрос:" if lang=="ru" else "✍️ Write your question:"
    await cb.message.edit_text(text)
    await state.update_data(lang=lang)
    await state.set_state(ContactTeacher.waiting_message)
    await cb.answer()

@dp.message(ContactTeacher.waiting_message)
async def receive_contact_message(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    user = msg.from_user
    username = f"@{user.username}" if user.username else f"ID:{user.id}"

    await bot.send_message(
        TUTOR_ID,
        f"💬 <b>Сообщение от ученика</b>\n\n"
        f"👤 {user.full_name} ({username})\n\n"
        f"📝 {msg.text}",
        parse_mode="HTML"
    )
    reply = "Сообщение отправлено 🌿\n\nПреподаватель ответит вам при первой возможности." if lang=="ru" \
        else "Message sent 🌿\n\nThe teacher will reply at the earliest opportunity."

    student = db.get_student_by_telegram(msg.from_user.id)
    pending = db.get_pending_application(msg.from_user.id) if not student else None
    kb = student_kb(lang, has_pending=bool(pending)) if student else new_user_kb(lang)
    await msg.answer(reply, reply_markup=kb)
    await state.clear()

# ── /apply — заявка ───────────────────────────────────────────────────────────

async def start_apply_flow(msg_or_cb, state: FSMContext, lang: str):
    """Запускает анкету — используется из кнопки и callback"""
    student = db.get_student_by_telegram(
        msg_or_cb.from_user.id if hasattr(msg_or_cb, 'from_user') else msg_or_cb.message.from_user.id
    )
    if student:
        # Существующий ученик → записаться на занятие
        await start_book_lesson(msg_or_cb, state, student, lang)
        return

    await state.update_data(lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇺🇸 English", callback_data="lang_en"),
    ]])
    text = "Выберите язык / Choose language:"
    if hasattr(msg_or_cb, 'message'):
        await msg_or_cb.message.edit_text(text, reply_markup=kb)
        await msg_or_cb.answer()
    else:
        await msg_or_cb.answer(text, reply_markup=kb)
    await state.set_state(ApplyForm.lang)

@dp.message(Command("apply"))
@dp.message(F.text.in_({"📝 Записаться на занятия", "📝 Apply for lessons"}))
async def cmd_apply(msg: Message, state: FSMContext):
    lang = get_lang(msg.from_user)
    await start_apply_flow(msg, state, lang)

@dp.callback_query(F.data == "start_apply")
async def cb_start_apply(cb: CallbackQuery, state: FSMContext):
    lang = get_lang(cb.from_user)
    await start_apply_flow(cb, state, lang)

@dp.callback_query(ApplyForm.lang, F.data.startswith("lang_"))
async def apply_lang(cb: CallbackQuery, state: FSMContext):
    lang = cb.data.split("_")[1]
    await state.update_data(lang=lang)
    await cb.message.edit_text(t(lang, "ask_name"))
    await state.set_state(ApplyForm.name)
    await cb.answer()

@dp.message(ApplyForm.name)
async def apply_name(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    await state.update_data(name=msg.text)
    await msg.answer(t(lang, "ask_level"))
    await state.set_state(ApplyForm.level)

@dp.message(ApplyForm.level)
async def apply_level(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    await state.update_data(level=msg.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang,"freq_2x"), callback_data="freq_2x"),
        InlineKeyboardButton(text=t(lang,"freq_3x"), callback_data="freq_3x"),
    ]])
    await msg.answer(t(lang, "ask_frequency"), reply_markup=kb)
    await state.set_state(ApplyForm.frequency)

@dp.callback_query(ApplyForm.frequency, F.data.startswith("freq_"))
async def apply_freq(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    await state.update_data(frequency=cb.data.split("_")[1])
    await cb.message.edit_text(t(lang, "ask_time"))
    await state.set_state(ApplyForm.wishes)
    await cb.answer()

@dp.message(ApplyForm.wishes)
async def apply_wishes(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    await state.update_data(wishes=msg.text)
    ask = ("Укажите ваш Telegram username (например @username)\nЭто нужно чтобы преподаватель мог написать вам напрямую."
           if lang=="ru" else
           "Please share your Telegram username (e.g. @username)\nSo the teacher can contact you directly.")
    await msg.answer(ask)
    await state.set_state(ApplyForm.username)

@dp.message(ApplyForm.username)
async def apply_username(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    username = msg.text.strip().lstrip('@') if msg.text.strip() not in ('-','нет','no','—') else None
    await state.update_data(username=username or msg.from_user.username)
    await msg.answer(t(lang, "ask_message"))
    await state.set_state(ApplyForm.message)

@dp.message(ApplyForm.message)
async def apply_done(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    tg_username = data.get('username') or msg.from_user.username
    app = db.create_application({
        "telegram_id":    msg.from_user.id,
        "name":           data["name"],
        "level":          data.get("level"),
        "frequency":      data.get("frequency"),
        "preferred_time": data.get("wishes"),
        "message":        msg.text if msg.text.lower() not in ("нет","no","-") else None,
        "lang":           lang,
        "status":         "new",
        "username":       tg_username,
    })

    pending = db.get_pending_application(msg.from_user.id)
    await msg.answer(t(lang, "applied"), reply_markup=new_user_kb(lang) if not db.get_student_by_telegram(msg.from_user.id)
                     else student_kb(lang, has_pending=True))

    freq_label = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(data.get("frequency",""),"")
    username_line = f"@{tg_username}" if tg_username else f"ID: {msg.from_user.id}"
    notif = (
        f"📬 <b>Новая заявка!</b>\n\n"
        f"👤 {data['name']}\n"
        f"📊 Уровень: {data.get('level','—')}\n"
        f"📅 Частота: {freq_label}\n"
        f"⏰ Пожелания: {data.get('wishes','—')}\n"
        f"💬 {msg.text}\n"
        f"🌐 {'🇷🇺' if lang=='ru' else '🇺🇸'}\n"
        f"✉️ {username_line}"
    )
    kb = None
    if tg_username:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✉️ Написать @{tg_username}", url=f"https://t.me/{tg_username}")
        ]])
    await bot.send_message(TUTOR_ID, notif, parse_mode="HTML", reply_markup=kb)
    await state.clear()

# ── Запись на занятие (существующий ученик) ───────────────────────────────────

async def start_book_lesson(msg_or_cb, state: FSMContext, student: dict, lang: str):
    """Показывает календарь доступных дат"""
    available = get_available_dates()
    if not available:
        text = ("К сожалению, в ближайший месяц свободных окон нет.\n\nОтправить заявку преподавателю?"
                if lang=="ru" else
                "Unfortunately, there are no available slots in the next month.\n\nSend a request to the teacher?")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📩 Отправить заявку" if lang=="ru" else "📩 Send request",
                                 callback_data="book_no_slots_request"),
            InlineKeyboardButton(text="❌ Отмена" if lang=="ru" else "❌ Cancel",
                                 callback_data="book_cancel"),
        ]])
        if hasattr(msg_or_cb, 'message'):
            await msg_or_cb.message.edit_text(text, reply_markup=kb)
            await msg_or_cb.answer()
        else:
            await msg_or_cb.answer(text, reply_markup=kb)
        return

    await state.update_data(student_id=student["id"], student_name=student["name"], lang=lang)

    # Показываем до 10 ближайших дат кнопками
    days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    buttons = []
    for d, slots in available[:14]:
        dow = days_ru[d.weekday()]
        label = f"{dow} {fmt_date(d)} — {len(slots)} окн{'о' if len(slots)==1 else 'а' if len(slots)<5 else 'ов'}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"bookdate_{d.isoformat()}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена" if lang=="ru" else "❌ Cancel",
                                         callback_data="book_cancel")])

    text = ("📅 <b>Выберите дату занятия</b>\n\nЗапись доступна минимум за 2 дня и не более чем на месяц вперёд."
            if lang=="ru" else
            "📅 <b>Choose a lesson date</b>\n\nBooking is available at least 2 days in advance, up to 1 month ahead.")

    if hasattr(msg_or_cb, 'message'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML",
                                           reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await msg_or_cb.answer()
    else:
        await msg_or_cb.answer(text, parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BookLesson.date_select)

@dp.message(F.text.in_({"🗓 Записаться на занятие", "🗓 Book a lesson"}))
async def cmd_book_lesson(msg: Message, state: FSMContext):
    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы. Подайте заявку." if lang=="ru"
                         else "You are not registered yet. Please apply.")
        return
    lang = student.get("telegram_lang", lang)
    await start_book_lesson(msg, state, student, lang)

@dp.callback_query(BookLesson.date_select, F.data.startswith("bookdate_"))
async def book_date_selected(cb: CallbackQuery, state: FSMContext):
    date_str = cb.data.replace("bookdate_", "")
    selected_date = date.fromisoformat(date_str)
    data = await state.get_data()
    lang = data.get("lang", "ru")

    # Проверяем ограничение по дате
    if selected_date < min_booking_date():
        await cb.answer("Эта дата недоступна для записи." if lang=="ru"
                        else "This date is not available.", show_alert=True)
        return

    slots = get_free_slots(selected_date)
    if not slots:
        # Ищем ближайшую свободную дату
        next_avail = find_next_available(selected_date)
        if next_avail:
            nd, ns = next_avail
            days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
            text = (f"На {fmt_date(selected_date)} свободного времени нет.\n\n"
                    f"Ближайшая доступная дата — {days_ru[nd.weekday()]}, {fmt_date(nd)}\n"
                    f"Свободные окна: {', '.join(ns[:5])}"
                    if lang=="ru" else
                    f"No available slots on {fmt_date(selected_date)}.\n\n"
                    f"Next available date — {nd.strftime('%A')}, {fmt_date(nd)}\n"
                    f"Available times: {', '.join(ns[:5])}")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"📅 Показать время на {fmt_date(nd)}" if lang=="ru" else f"📅 Show times on {fmt_date(nd)}",
                    callback_data=f"bookdate_{nd.isoformat()}"
                )],
                [InlineKeyboardButton(text="🔙 Другая дата" if lang=="ru" else "🔙 Other date",
                                      callback_data="book_back_to_dates")],
                [InlineKeyboardButton(text="❌ Отмена" if lang=="ru" else "❌ Cancel",
                                      callback_data="book_cancel")],
            ])
            await cb.message.edit_text(text, reply_markup=kb)
        else:
            text = ("К сожалению, в ближайший месяц свободных окон нет."
                    if lang=="ru" else "No available slots in the next month.")
            await cb.message.edit_text(text)
        await cb.answer()
        return

    await state.update_data(selected_date=date_str)

    # Показываем свободные окна кнопками
    buttons = []
    row = []
    for slot in slots:
        row.append(InlineKeyboardButton(text=f"⏰ {slot}", callback_data=f"booktime_{slot}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row: buttons.append(row)

    days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    dow = days_ru[selected_date.weekday()]
    buttons.append([InlineKeyboardButton(text="🔙 Другая дата" if lang=="ru" else "🔙 Other date",
                                         callback_data="book_back_to_dates")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена" if lang=="ru" else "❌ Cancel",
                                         callback_data="book_cancel")])

    text = (f"📅 <b>{dow}, {fmt_date(selected_date)}</b>\n\nВыберите удобное время:"
            if lang=="ru" else
            f"📅 <b>{selected_date.strftime('%A')}, {fmt_date(selected_date)}</b>\n\nChoose a time:")
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BookLesson.time_select)
    await cb.answer()

@dp.callback_query(BookLesson.date_select, F.data == "book_back_to_dates")
@dp.callback_query(BookLesson.time_select, F.data == "book_back_to_dates")
async def book_back_to_dates(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    student = db.get_student_by_telegram(cb.from_user.id)
    if student:
        await start_book_lesson(cb, state, student, lang)
    await cb.answer()

@dp.callback_query(BookLesson.time_select, F.data.startswith("booktime_"))
async def book_time_selected(cb: CallbackQuery, state: FSMContext):
    time_str = cb.data.replace("booktime_", "")
    data = await state.get_data()
    lang = data.get("lang", "ru")
    selected_date = date.fromisoformat(data["selected_date"])

    # Повторная проверка доступности
    slots = get_free_slots(selected_date)
    if time_str not in slots:
        await cb.answer("Это время уже занято. Выберите другое." if lang=="ru"
                        else "This time is no longer available.", show_alert=True)
        return

    await state.update_data(selected_time=time_str)
    days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    dow = days_ru[selected_date.weekday()]

    text = (f"📋 <b>Подтвердите запрос:</b>\n\n"
            f"📅 {dow}, {fmt_date(selected_date)}\n"
            f"⏰ {time_str}\n\n"
            f"Преподаватель рассмотрит и утвердит занятие после подтверждения оплаты."
            if lang=="ru" else
            f"📋 <b>Confirm your request:</b>\n\n"
            f"📅 {selected_date.strftime('%A')}, {fmt_date(selected_date)}\n"
            f"⏰ {time_str}\n\n"
            f"The teacher will review and confirm after payment.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить запрос" if lang=="ru" else "✅ Send request",
                              callback_data="book_confirm")],
        [InlineKeyboardButton(text="🔙 Другое время" if lang=="ru" else "🔙 Other time",
                              callback_data=f"bookdate_{data['selected_date']}")],
        [InlineKeyboardButton(text="❌ Отмена" if lang=="ru" else "❌ Cancel",
                              callback_data="book_cancel")],
    ])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await state.set_state(BookLesson.confirm)
    await cb.answer()

@dp.callback_query(BookLesson.confirm, F.data == "book_confirm")
async def book_confirmed(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    student_id = data["student_id"]
    student_name = data["student_name"]
    selected_date = data["selected_date"]
    selected_time = data["selected_time"]

    # Финальная проверка доступности
    slots = get_free_slots(date.fromisoformat(selected_date))
    if selected_time not in slots:
        await cb.answer("Это время уже занято. Выберите другое." if lang=="ru"
                        else "This time slot is no longer available.", show_alert=True)
        await state.clear()
        return

    # Сохраняем заявку с данными занятия
    app_id = str(uuid.uuid4())
    req_id = app_id.replace("-", "")
    db.create_application({
        "id":           app_id,
        "telegram_id":  cb.from_user.id,
        "name":         student_name,
        "level":        "",
        "frequency":    selected_time,    # время
        "preferred_time": f"{selected_date} {selected_time}",
        "message":      student_id,       # student_id
        "lang":         lang,
        "status":       "new",
        "username":     str(cb.from_user.id),
    })

    # Подтверждение ученику
    days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    d = date.fromisoformat(selected_date)
    dow = days_ru[d.weekday()]
    date_fmt = f"{dow}, {fmt_date(d)}"

    await cb.message.edit_text(
        f"✅ Запрос отправлен!\n\n📅 {date_fmt}\n⏰ {selected_time}\n\n"
        f"Ожидайте подтверждения от преподавателя."
        if lang=="ru" else
        f"✅ Request sent!\n\n📅 {date_fmt}\n⏰ {selected_time}\n\n"
        f"Please wait for the teacher's confirmation."
    )

    # Уведомление преподавателю — ОДНА кнопка, одно нажатие
    notif = (
        f"📬 <b>Запрос на занятие!</b>\n\n"
        f"👤 {student_name}\n"
        f"📅 {date_fmt}\n"
        f"⏰ {selected_time}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Утвердить — {date_fmt} {selected_time}",
                             callback_data=f"apl_{req_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rjl_{req_id}"),
    ]])
    await bot.send_message(TUTOR_ID, notif, parse_mode="HTML", reply_markup=kb)
    await state.clear()
    await cb.answer()

@dp.callback_query(F.data == "book_cancel")
async def book_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = get_lang(cb.from_user)
    student = db.get_student_by_telegram(cb.from_user.id)
    if student:
        lang = student.get("telegram_lang", lang)
        await cb.message.edit_text("Отменено." if lang=="ru" else "Cancelled.")
    else:
        await cb.message.edit_text("Отменено." if lang=="ru" else "Cancelled.")
    await cb.answer()

@dp.callback_query(F.data == "book_no_slots_request")
async def book_no_slots_request(cb: CallbackQuery, state: FSMContext):
    lang = get_lang(cb.from_user)
    student = db.get_student_by_telegram(cb.from_user.id)
    if student:
        await start_apply_flow(cb, state, lang)
    await cb.answer()

# ── Утверждение занятия преподавателем (ОДНО нажатие) ────────────────────────

@dp.callback_query(F.data.startswith("apl_"))
async def approve_lesson_request(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID:
        await cb.answer("Нет доступа", show_alert=True); return

    req_id = cb.data.replace("apl_", "")
    log.info(f"approve_lesson: req_id={req_id}")

    app = db.get_application(req_id)

    # Fallback: последняя новая заявка с lesson_request типом
    if not app:
        all_apps = db.get_new_applications()
        lesson_apps = [a for a in all_apps if str(a.get("message","")).count("-") == 4]  # UUID формат
        if lesson_apps:
            app = sorted(lesson_apps, key=lambda a: a.get("created_at",""))[-1]
            log.info(f"approve_lesson: using fallback app={app['id']}")
        else:
            await cb.answer("Заявка не найдена", show_alert=True); return

    # Защита от повторного подтверждения
    if app.get("status") in ("approved", "rejected", "cancelled"):
        await cb.message.edit_text(
            f"{'Это занятие уже было подтверждено.' if app['status']=='approved' else 'Заявка уже обработана.'}"
        )
        await cb.answer(); return

    # Получаем данные
    student_id    = app.get("message", "")  # student_id хранится в message
    time_text     = app.get("frequency", "")
    preferred     = app.get("preferred_time", "")
    lang          = app.get("lang", "ru")
    student_tg_id = app["telegram_id"]

    # Парсим дату из preferred_time (формат "2026-07-17 11:00")
    parts = preferred.strip().split()
    lesson_date_str = parts[0] if parts else ""
    lesson_time     = parts[1] if len(parts) > 1 else time_text

    # Повторная проверка доступности
    if lesson_date_str:
        try:
            ld = date.fromisoformat(lesson_date_str)
            slots = get_free_slots(ld)
            if lesson_time and lesson_time not in slots:
                await cb.answer(f"Время {lesson_time} уже занято!", show_alert=True)
                return
        except Exception as e:
            log.warning(f"Date check failed: {e}")

    # Создаём занятие (одна операция)
    session = {
        "id":         str(uuid.uuid4()),
        "student_id": student_id,
        "date":       lesson_date_str or date.today().isoformat(),
        "time":       lesson_time,
        "held":       False,
        "paid":       False,
    }

    try:
        db.add_session_direct(session)
        db.update_application(app["id"], "approved")
        log.info(f"approve_lesson: session created {session['id']}, app {app['id']} approved")
    except Exception as e:
        log.error(f"approve_lesson error: {e}")
        await cb.answer("Ошибка при создании занятия", show_alert=True); return

    # Форматируем дату для сообщений
    days_ru = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    try:
        ld = date.fromisoformat(lesson_date_str)
        dow = days_ru[ld.weekday()]
        date_fmt = f"{dow}, {fmt_date(ld)}"
    except Exception:
        date_fmt = lesson_date_str

    # Обновляем сообщение преподавателю
    await cb.message.edit_text(
        f"✅ <b>Занятие подтверждено!</b>\n\n"
        f"👤 Ученик: {app['name']}\n"
        f"📅 {date_fmt}\n"
        f"⏰ {lesson_time}",
        parse_mode="HTML"
    )

    # Уведомляем ученика
    confirmed_text = t(lang, "lesson_confirmed", date=date_fmt, time=lesson_time)
    try:
        await bot.send_message(student_tg_id, confirmed_text)
    except Exception as e:
        log.warning(f"Could not notify student: {e}")

    await cb.answer()

@dp.callback_query(F.data.startswith("rjl_"))
async def reject_lesson_request(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID:
        await cb.answer("Нет доступа", show_alert=True); return

    req_id = cb.data.replace("rjl_", "")
    app = db.get_application(req_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True); return

    db.update_application(app["id"], "rejected")
    student_tg_id = app["telegram_id"]
    lang = app.get("lang", "ru")

    await cb.message.edit_text("❌ Запрос на занятие отклонён.")

    text = ("😔 К сожалению, преподаватель не может провести занятие в указанное время.\n\nПопробуйте выбрать другое время."
            if lang=="ru" else
            "😔 Unfortunately, the teacher is not available at the requested time.\n\nPlease try a different time.")
    try:
        await bot.send_message(student_tg_id, text)
    except Exception as e:
        log.warning(f"Could not notify student: {e}")
    await cb.answer()

# ── /schedule — расписание ученика ────────────────────────────────────────────

@dp.message(F.text.in_({"📅 Моё следующее занятие", "📅 My next lesson"}))
@dp.message(Command("schedule"))
async def cmd_schedule(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы. Подайте заявку." ); return
    lang = student.get("telegram_lang", "ru")
    sessions = db.get_sessions_for_student(student["id"])
    today_str = today_seoul().isoformat()
    upcoming = sorted([s for s in sessions if s["date"] >= today_str and not s["held"]], key=lambda s: s["date"])

    sched = db.get_student_schedule(student["id"])
    lines = []
    if sched:
        lines.append("📅 <b>Ваше расписание:</b>\n" if lang=="ru" else "📅 <b>Your schedule:</b>\n")
        for row in sched:
            lines.append(f"  {DAYS_RU[row['dow']]} — {row['time']}")
        lines.append("")

    if upcoming:
        lines.append("<b>Ближайшие занятия:</b>" if lang=="ru" else "<b>Upcoming lessons:</b>")
        for s in upcoming[:5]:
            d = date.fromisoformat(s["date"])
            dow = DAYS_RU[d.weekday()]
            time_str = f" в {s['time']}" if s.get("time") else ""
            lines.append(f"• {dow} {fmt_date(d)}{time_str}")
    else:
        lines.append("📅 Ближайших занятий нет." if lang=="ru" else "📅 No upcoming lessons.")

    await msg.answer("\n".join(lines) if lines else "Нет данных", parse_mode="HTML")

# ── /payment ──────────────────────────────────────────────────────────────────

@dp.message(F.text.in_({"💳 Оплата", "💳 Payment"}))
@dp.message(Command("payment"))
async def cmd_payment(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы."); return
    lang = student.get("telegram_lang", "ru")
    debt = db.get_student_debt(student["id"])
    if debt == 0:
        await msg.answer("✅ Оплата в порядке!" if lang=="ru" else "✅ All paid!")
    else:
        fmt = f"{debt:,}".replace(",", " ")
        text = (f"💳 Задолженность: <b>{fmt} ₩</b>\n\nПожалуйста, оплатите при возможности."
                if lang=="ru" else f"💳 Balance: <b>{fmt} ₩</b>\n\nPlease pay when you can.")
        await msg.answer(text, parse_mode="HTML")

# ── Привязка существующего ученика ────────────────────────────────────────────

@dp.message(Command("link"))
async def cmd_link(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        lang = student.get("telegram_lang", "ru")
        await msg.answer(f"Вы уже привязаны как {student['name']} ✅" if lang=="ru"
                         else f"You are already linked as {student['name']} ✅")
        return
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Напишите команду с вашим именем:\n<code>/link Екатерина</code>", parse_mode="HTML")
        return
    search = parts[1].strip().lower()
    all_students = db.get_all_students()
    found = [s for s in all_students if search in s["name"].lower()]
    if not found:
        await msg.answer(f"Ученик с именем <b>{parts[1]}</b> не найден.\n\nПроверьте написание или подайте заявку: /apply",
                         parse_mode="HTML"); return
    if len(found) > 1:
        names = "\n".join(f"• {s['name']}" for s in found)
        await msg.answer(f"Найдено несколько:\n{names}\n\nУточните полное имя.", parse_mode="HTML"); return
    student = found[0]
    db.update_student(student["id"], {"telegram_id": msg.from_user.id, "telegram_lang": "ru",
                                       "username": msg.from_user.username or ""})
    await msg.answer(f"✅ Готово! Вы привязаны как <b>{student['name']}</b>\n\n/schedule — занятия\n/payment — оплата",
                     parse_mode="HTML", reply_markup=student_kb("ru"))
    await bot.send_message(TUTOR_ID,
        f"🔗 <b>Ученик привязал аккаунт</b>\n\n👤 {student['name']}\n✉️ {'@'+msg.from_user.username if msg.from_user.username else 'без username'}",
        parse_mode="HTML")

# ── Отзыв заявки учеником ─────────────────────────────────────────────────────

@dp.message(F.text.in_({"🚫 Отозвать заявку", "🚫 Cancel application"}))
async def cancel_own_application(msg: Message):
    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        await msg.answer("Вы уже наш ученик." if lang=="ru" else "You are already our student."); return
    pending = db.get_pending_application(msg.from_user.id)
    if not pending:
        await msg.answer("У вас нет активных заявок." if lang=="ru" else "No active applications."); return
    db.update_application(pending["id"], "cancelled")
    await msg.answer(
        "🚫 Заявка отозвана.\n\nВы можете подать новую заявку в любое время." if lang=="ru"
        else "🚫 Application cancelled.\n\nYou can apply again at any time.",
        reply_markup=new_user_kb(lang)
    )
    await bot.send_message(TUTOR_ID, f"🚫 <b>Ученик отозвал заявку</b>\n\n👤 {pending['name']}", parse_mode="HTML")

# ── Панель преподавателя ──────────────────────────────────────────────────────

@dp.message(Command("schedule_set"))
@dp.message(F.text == "📅 Расписание")
async def cmd_schedule_menu(msg: Message, state: FSMContext):
    if msg.from_user.id != TUTOR_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗓 Моё расписание на эту неделю", callback_data="smenu_week")],
        [InlineKeyboardButton(text="📋 Список учеников с расписанием", callback_data="smenu_list")],
        [InlineKeyboardButton(text="✏️ Редактировать расписание ученика", callback_data="smenu_edit")],
        [InlineKeyboardButton(text="➕ Утвердить расписание новому ученику", callback_data="smenu_new")],
    ])
    await msg.answer("📅 <b>Расписание</b>", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "smenu_week")
async def smenu_week(cb: CallbackQuery):
    today = today_seoul()
    monday = today - timedelta(days=today.weekday())
    students = db.get_all_students()
    student_map = {s["id"]: s["name"] for s in students}
    week_data = {}
    for i in range(7):
        day = monday + timedelta(days=i)
        try:
            sessions = db.get_sessions_for_date(day.isoformat())
            if sessions:
                week_data[day] = sessions
        except Exception:
            pass
    if not week_data:
        await cb.message.edit_text("📅 На эту неделю занятий не запланировано.")
        await cb.answer(); return
    lines = [f"📅 <b>Расписание {monday.strftime('%d.%m')}–{(monday+timedelta(days=6)).strftime('%d.%m')}</b>\n"]
    for i in range(7):
        day = monday + timedelta(days=i)
        if day not in week_data: continue
        mark = "🔵 " if day == today else ""
        lines.append(f"{mark}<b>{DAYS_RU[i]}, {fmt_date(day)}</b>")
        for s in sorted(week_data[day], key=lambda x: x.get("time","") or ""):
            name = student_map.get(s["student_id"], "?")
            time_str = f" {s['time']}" if s.get("time") else ""
            held = " ✓" if s.get("held") else ""
            lines.append(f"  👤 {name}{time_str}{held}")
        lines.append("")
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "smenu_list")
async def smenu_list(cb: CallbackQuery):
    students = db.get_all_students()
    if not students:
        await cb.answer("Учеников нет", show_alert=True); return
    lines = ["👥 <b>Расписание учеников:</b>\n"]
    for s in students:
        sched = db.get_student_schedule(s["id"])
        if sched:
            sched_str = ", ".join(f"{DAYS_RU[r['dow']]} {r['time']}" for r in sched)
            lines.append(f"👤 <b>{s['name']}</b>\n   📅 {sched_str}")
        else:
            lines.append(f"👤 <b>{s['name']}</b>\n   — не задано")
        lines.append("")
    await cb.message.edit_text("\n".join(lines), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "smenu_edit")
async def smenu_edit(cb: CallbackQuery, state: FSMContext):
    students = db.get_all_students()
    if not students:
        await cb.answer("Учеников нет", show_alert=True); return
    buttons = [[InlineKeyboardButton(text=f"👤 {s['name']}", callback_data=f"sedit_{s['id']}")]
               for s in students]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="sedit_cancel")])
    await cb.message.edit_text("✏️ <b>Выбери ученика:</b>", parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@dp.callback_query(F.data == "smenu_new")
async def smenu_new(cb: CallbackQuery, state: FSMContext):
    await cb.message.delete()
    apps = db.get_new_applications()
    # Только заявки новых учеников (не lesson_request)
    new_student_apps = [a for a in apps if not str(a.get("message","")).count("-") == 4]
    if not new_student_apps:
        await cb.message.answer("📭 Нет новых заявок от новых учеников.\n\nДля утверждения: /schedule_set")
        await cb.answer(); return
    buttons = []
    for app in new_student_apps:
        freq = {"2x":"2×/нед","3x":"3×/нед"}.get(app.get("frequency",""),"")
        buttons.append([InlineKeyboardButton(
            text=f"✅ {app['name']} ({freq})", callback_data=f"pickapp_{app['id']}")])
    await cb.message.answer("📋 <b>Новые ученики:</b>", parse_mode="HTML",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(ScheduleSetup.select_app)
    await cb.answer()

@dp.callback_query(F.data == "sedit_cancel")
async def sedit_cancel(cb: CallbackQuery):
    await cb.message.edit_text("Отменено."); await cb.answer()

@dp.callback_query(F.data.startswith("sedit_"))
async def sedit_student(cb: CallbackQuery, state: FSMContext):
    if cb.data == "sedit_cancel": return
    student_id = cb.data.replace("sedit_", "")
    all_students = db.get_all_students()
    student = next((s for s in all_students if s["id"] == student_id), None)
    if not student:
        await cb.answer("Ученик не найден", show_alert=True); return
    sched = db.get_student_schedule(student_id)
    current = "\n".join(f"  {DAYS_RU[r['dow']]} — {r['time']}" for r in sched) if sched else "  — не задано"
    await state.update_data(edit_student_id=student_id, app={"name": student["name"],
                             "level": student.get("level",""), "telegram_id": student.get("telegram_id"),
                             "message":""}, app_id=None, selected_days=[], frequency=student.get("frequency","2x"))
    await cb.message.edit_text(
        f"✏️ <b>{student['name']}</b>\n\nТекущее расписание:\n{current}\n\nВыбери новые <b>дни недели</b>:",
        parse_mode="HTML", reply_markup=days_kb([]))
    await state.set_state(ScheduleSetup.days)
    await cb.answer()

# ── ScheduleSetup FSM ─────────────────────────────────────────────────────────

@dp.callback_query(ScheduleSetup.select_app, F.data.startswith("pickapp_"))
async def pick_application(cb: CallbackQuery, state: FSMContext):
    app_id = cb.data.replace("pickapp_", "")
    app = db.get_application(app_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True); return
    await state.update_data(app_id=app_id, app=app, selected_days=[])
    freq = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(app.get("frequency",""),"")
    await cb.message.edit_text(
        f"👤 <b>{app['name']}</b>\n📊 {app.get('level','—')} · {freq}\n⏰ {app.get('preferred_time','—')}\n\n<b>Частота занятий:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="2 раза в неделю", callback_data="tfreq_2x"),
            InlineKeyboardButton(text="3 раза в неделю", callback_data="tfreq_3x"),
        ]]))
    await state.set_state(ScheduleSetup.frequency)
    await cb.answer()

@dp.callback_query(ScheduleSetup.frequency, F.data.startswith("tfreq_"))
async def confirm_freq(cb: CallbackQuery, state: FSMContext):
    await state.update_data(frequency=cb.data.replace("tfreq_",""), selected_days=[])
    await cb.message.edit_text("📆 <b>Выбери дни недели:</b>", parse_mode="HTML", reply_markup=days_kb([]))
    await state.set_state(ScheduleSetup.days)
    await cb.answer()

@dp.callback_query(ScheduleSetup.days, F.data.startswith("tday_"))
async def toggle_day(cb: CallbackQuery, state: FSMContext):
    idx = int(cb.data.replace("tday_",""))
    data = await state.get_data()
    selected = data.get("selected_days",[])
    if idx in selected: selected.remove(idx)
    else: selected.append(idx)
    await state.update_data(selected_days=selected)
    await cb.message.edit_reply_markup(reply_markup=days_kb(selected))
    await cb.answer()

@dp.callback_query(ScheduleSetup.days, F.data == "tdays_done")
async def days_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = sorted(data.get("selected_days",[]))
    if not selected:
        await cb.answer("Выбери хотя бы один день!", show_alert=True); return
    await state.update_data(selected_days=selected, day_times={}, time_day_idx=0)
    first_day = DAYS_RU[selected[0]]
    await cb.message.edit_text(f"⏰ <b>Время для {first_day}?</b>\n\nНапример: <code>11:00</code>", parse_mode="HTML")
    await state.set_state(ScheduleSetup.day_times)
    await cb.answer()

@dp.message(ScheduleSetup.day_times)
async def confirm_day_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    selected = data["selected_days"]
    day_times = data.get("day_times",{})
    idx = data.get("time_day_idx",0)
    day_times[str(selected[idx])] = msg.text.strip()
    await state.update_data(day_times=day_times)
    next_idx = idx + 1
    if next_idx < len(selected):
        await state.update_data(time_day_idx=next_idx)
        await msg.answer(f"⏰ <b>Время для {DAYS_RU[selected[next_idx]]}?</b>\n\nНапример: <code>15:00</code>",
                         parse_mode="HTML")
    else:
        await state.update_data(time_day_idx=0)
        await msg.answer(
            "🎁 <b>Бесплатные занятия?</b>", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Да, 8 занятий", callback_data="free_yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data="free_no"),
            ]]))
        await state.set_state(ScheduleSetup.has_free)

@dp.callback_query(ScheduleSetup.has_free, F.data.startswith("free_"))
async def confirm_free(cb: CallbackQuery, state: FSMContext):
    has_free = cb.data == "free_yes"
    await state.update_data(has_free=has_free)
    data = await state.get_data()
    app = data["app"]
    day_times = data.get("day_times",{})
    sched_lines = "\n".join(f"  {DAYS_RU[int(d)]} — {t}" for d, t in sorted(day_times.items(), key=lambda x: int(x[0])))
    freq_label = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(data.get("frequency",""),"")

    # Предпросмотр — показываем сколько занятий будет создано
    import calendar as cal2
    today = today_seoul()
    preview_sessions = generate_sessions_with_time("PREVIEW", day_times, today.year, today.month)
    days_left = (date(today.year, today.month, cal2.monthrange(today.year, today.month)[1]) - today).days
    if days_left < 14:
        nm = today.month+1 if today.month<12 else 1
        ny = today.year if today.month<12 else today.year+1
        preview_sessions += generate_sessions_with_time("PREVIEW", day_times, ny, nm)

    await cb.message.edit_text(
        f"📋 <b>Подтверди расписание:</b>\n\n"
        f"👤 {app['name']}\n"
        f"📅 {freq_label}\n"
        f"📆 Дни и время:\n{sched_lines}\n"
        f"🎁 Бесплатных: {'8 занятий' if has_free else 'нет'}\n"
        f"📆 Создаётся занятий: <b>{len(preview_sessions)}</b>\n\nВсё верно?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="sched_confirm"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="sched_restart"),
        ]]))
    await state.set_state(ScheduleSetup.confirm)
    await cb.answer()

@dp.callback_query(ScheduleSetup.confirm, F.data == "sched_restart")
async def sched_restart(cb: CallbackQuery, state: FSMContext):
    await state.update_data(selected_days=[])
    await cb.message.edit_text("📆 <b>Выбери дни недели заново:</b>", parse_mode="HTML", reply_markup=days_kb([]))
    await state.set_state(ScheduleSetup.days)
    await cb.answer()

@dp.callback_query(ScheduleSetup.confirm, F.data == "sched_confirm")
async def sched_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    app  = data["app"]
    edit_student_id = data.get("edit_student_id")
    day_times = data.get("day_times", {})

    import calendar as cal2
    today = today_seoul()

    if edit_student_id:
        all_students = db.get_all_students()
        student = next((s for s in all_students if s["id"] == edit_student_id), None)
        if not student:
            await cb.message.edit_text("❌ Ученик не найден.")
            await state.clear(); await cb.answer(); return
    else:
        student = db.create_student({
            "name":         app["name"], "level": app.get("level",""),
            "start_date":   today.isoformat(), "has_free": data["has_free"],
            "free_count":   8 if data["has_free"] else 0, "frequency": data["frequency"],
            "payment_type": "perSession", "notes": app.get("message") or "",
            "telegram_id":  app.get("telegram_id"), "telegram_lang": app.get("lang","ru"),
        })

    sessions = generate_sessions_with_time(student["id"], day_times, today.year, today.month)
    days_left = (date(today.year, today.month, cal2.monthrange(today.year, today.month)[1]) - today).days
    if days_left < 14:
        nm = today.month+1 if today.month<12 else 1
        ny = today.year if today.month<12 else today.year+1
        sessions += generate_sessions_with_time(student["id"], day_times, ny, nm)

    for s in sessions:
        db.add_session_direct(s)
    db.save_student_schedule(student["id"], day_times)

    if not edit_student_id and data.get("app_id"):
        try: db.update_application(data["app_id"], "approved")
        except Exception: pass

    sched_lines = "\n".join(f"  {DAYS_RU[int(d)]} — {t}" for d, t in sorted(day_times.items(), key=lambda x: int(x[0])))

    if edit_student_id:
        await cb.message.edit_text(
            f"✅ <b>Расписание обновлено!</b>\n\n👤 {student['name']}\n📆:\n{sched_lines}\n📅 Создано занятий: {len(sessions)}",
            parse_mode="HTML")
    else:
        await cb.message.edit_text(
            f"✅ <b>Готово!</b>\n\n👤 {app['name']} добавлен\n📆:\n{sched_lines}\n📅 Создано занятий: {len(sessions)}\n\nЗанятия в системе! 🎉",
            parse_mode="HTML")
        lang = app.get("lang","ru")
        try: await bot.send_message(app.get("telegram_id"), t(lang, "approved"))
        except Exception: pass
    await state.clear(); await cb.answer()

# ── Команды преподавателя ─────────────────────────────────────────────────────

@dp.message(F.text == "📋 Заявки")
async def cmd_applications(msg: Message, state: FSMContext):
    if msg.from_user.id != TUTOR_ID: return
    apps = db.get_new_applications()
    if not apps:
        await msg.answer("📭 Нет новых заявок."); return
    text = f"📋 <b>Новые заявки ({len(apps)}):</b>\n\n"
    buttons = []
    for app in apps:
        is_lesson = str(app.get("message","")).count("-") == 4
        pref = app.get("preferred_time","—")
        text += f"👤 <b>{app['name']}</b>\n"
        if is_lesson:
            text += f"📅 Запрос занятия: {pref}\n\n"
            req_id = app["id"].replace("-","")
            buttons.append([
                InlineKeyboardButton(text=f"✅ Утвердить — {app['name']}", callback_data=f"apl_{req_id}"),
                InlineKeyboardButton(text="❌", callback_data=f"rjl_{req_id}"),
            ])
        else:
            freq = {"2x":"2×/нед","3x":"3×/нед"}.get(app.get("frequency",""),"")
            text += f"📊 {app.get('level','—')} · {freq}\n⏰ {pref}\n\n"
            buttons.append([
                InlineKeyboardButton(text=f"✅ {app['name']}", callback_data=f"pickapp_{app['id']}"),
                InlineKeyboardButton(text="❌", callback_data=f"reject_{app['id']}_{app['telegram_id']}_{app.get('lang','ru')}"),
            ])
    await msg.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(ScheduleSetup.select_app)

@dp.callback_query(F.data.startswith("reject_"))
async def reject_application(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID: return
    parts = cb.data.split("_", 3)
    if len(parts) < 4: return
    _, app_id, student_tg_id, lang = parts
    db.update_application(app_id, "rejected")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("❌ Заявка отклонена.")
    text_ru = "😔 К сожалению, в данный момент нет свободных мест."
    text_en = "😔 Unfortunately, there are no available spots right now."
    try:
        await bot.send_message(int(student_tg_id), text_ru if lang=="ru" else text_en)
    except Exception: pass
    await cb.answer()

@dp.message(F.text == "👥 Ученики")
@dp.message(Command("students"))
async def cmd_students(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    students = db.get_all_students()
    if not students:
        await msg.answer("Учеников нет."); return
    lines = [f"👥 <b>Ученики ({len(students)}):</b>\n"]
    for s in students:
        freq = {"2x":"2×/нед","3x":"3×/нед"}.get(s["frequency"],"")
        tg = " ✅" if s.get("telegram_id") else " (не в боте)"
        lines.append(f"• {s['name']} — {freq}{tg}")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@dp.message(F.text == "💸 Должники")
@dp.message(Command("debtors"))
async def cmd_debtors(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    debtors = db.get_students_with_debt()
    if not debtors:
        await msg.answer("🎉 Долгов нет!"); return
    lines = ["💸 <b>Должники:</b>\n"]
    total = 0
    for s in debtors:
        fmt = f"{s['debt']:,}".replace(",", " ")
        lines.append(f"• {s['name']} — {fmt} ₩")
        total += s["debt"]
    lines.append(f"\n<b>Итого: {f'{total:,}'.replace(',', ' ')} ₩</b>")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@dp.message(F.text == "📣 Рассылка")
@dp.message(Command("remind"))
async def cmd_remind(msg: Message, state: FSMContext):
    if msg.from_user.id != TUTOR_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Напомнить об уроке",  callback_data="remind_lesson")],
        [InlineKeyboardButton(text="💳 Напомнить об оплате", callback_data="remind_payment")],
        [InlineKeyboardButton(text="📚💳 Всем об уроке",     callback_data="remind_lesson_all")],
        [InlineKeyboardButton(text="💳📢 Всем должникам",    callback_data="remind_payment_all")],
    ])
    await msg.answer("📣 <b>Что напомнить?</b>", parse_mode="HTML", reply_markup=kb)
    await state.set_state(RemindForm.type_select)

@dp.callback_query(RemindForm.type_select, F.data.startswith("remind_"))
async def remind_type(cb: CallbackQuery, state: FSMContext):
    rtype = cb.data
    if rtype == "remind_lesson_all":
        await cb.message.edit_text("⏳ Отправляю напоминания об уроках...")
        await send_lesson_reminders()
        await cb.message.edit_text("✅ Напоминания отправлены!")
        await state.clear(); await cb.answer(); return
    if rtype == "remind_payment_all":
        await cb.message.edit_text("⏳ Отправляю напоминания об оплате...")
        await send_payment_reminders()
        await cb.message.edit_text("✅ Напоминания об оплате отправлены!")
        await state.clear(); await cb.answer(); return
    students = db.get_all_students()
    with_tg = [s for s in students if s.get("telegram_id")]
    if not with_tg:
        await cb.message.edit_text("Нет учеников с Telegram аккаунтом.")
        await state.clear(); await cb.answer(); return
    await state.update_data(rtype=rtype)
    buttons = []
    for s in with_tg:
        label = f"👤 {s['name']}"
        if rtype == "remind_payment":
            debt = db.get_student_debt(s["id"])
            label += f" — {f'{debt:,}'.replace(',', ' ')} ₩" if debt else " ✅"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"rpick_{s['id']}")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="remind_cancel")])
    title = "📚 Кому напомнить об уроке?" if rtype=="remind_lesson" else "💳 Кому напомнить об оплате?"
    await cb.message.edit_text(f"<b>{title}</b>", parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(RemindForm.student_select)
    await cb.answer()

@dp.callback_query(RemindForm.student_select, F.data == "remind_cancel")
async def remind_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await cb.message.edit_text("Отменено."); await cb.answer()

@dp.callback_query(RemindForm.student_select, F.data.startswith("rpick_"))
async def remind_send(cb: CallbackQuery, state: FSMContext):
    student_id = cb.data.replace("rpick_","")
    data = await state.get_data(); rtype = data.get("rtype")
    student = next((s for s in db.get_all_students() if s["id"]==student_id), None)
    if not student or not student.get("telegram_id"):
        await cb.answer("Нет Telegram", show_alert=True); await state.clear(); return
    lang = student.get("telegram_lang","ru")

    if rtype == "remind_lesson":
        sessions = db.get_sessions_for_student(student_id)
        today_str = today_seoul().isoformat()
        upcoming = sorted([s for s in sessions if s["date"] >= today_str and not s["held"]], key=lambda s: s["date"])
        if not upcoming:
            await cb.message.edit_text(f"😔 У {student['name']} нет предстоящих занятий.")
            await state.clear(); await cb.answer(); return
        next_s = upcoming[0]
        d = date.fromisoformat(next_s["date"])
        day_diff = get_day_diff(next_s["date"])
        title = get_reminder_title(day_diff, lang)
        if title is None:
            await cb.message.edit_text(f"⚠️ Дата занятия уже прошла ({fmt_date(d)}).")
            await state.clear(); await cb.answer(); return
        date_fmt = fmt_date(d)
        time_str = next_s.get("time","")
        text = t(lang, "reminder_lesson", title=title, date=date_fmt, time=time_str)
        await bot.send_message(student["telegram_id"], text)
        await cb.message.edit_text(f"\u2705 Напоминание об уроке отправлено!\n\n\U0001f464 {student['name']}\n\U0001f4c5 {date_fmt} {time_str}")

    elif rtype == "remind_payment":
        debt = db.get_student_debt(student_id)
        if debt == 0:
            await cb.message.edit_text(f"✅ У {student['name']} нет долгов.")
            await state.clear(); await cb.answer(); return
        fmt = f"{debt:,}".replace(",", " ")
        text = t(lang, "reminder_payment", amount=fmt)
        await bot.send_message(student["telegram_id"], text)
        await cb.message.edit_text(f"\u2705 Напоминание об оплате отправлено!\n\n\U0001f464 {student['name']}\n\U0001f4b3 {fmt} \u20a9")

    await state.clear(); await cb.answer()

@dp.message(F.text == "❓ Помощь")
@dp.message(Command("help"))
async def cmd_help(msg: Message):
    if msg.from_user.id == TUTOR_ID:
        await msg.answer(
            "👩‍🏫 <b>Команды преподавателя:</b>\n\n"
            "/schedule_set — расписание учеников\n"
            "/remind — напоминания\n"
            "/students — все ученики\n"
            "/debtors — должники\n"
            "/testremind — тест напоминаний об уроках\n"
            "/testpayment — тест напоминаний об оплате",
            parse_mode="HTML")
    else:
        lang = get_lang(msg.from_user)
        student = db.get_student_by_telegram(msg.from_user.id)
        if student:
            lang = student.get("telegram_lang", lang)
            pending = db.get_pending_application(msg.from_user.id)
            await msg.answer(WELCOME_TEXT[lang], reply_markup=student_kb(lang, has_pending=bool(pending)))
        else:
            await msg.answer(WELCOME_TEXT[lang], reply_markup=new_user_kb(lang))

@dp.message(Command("testremind"))
async def cmd_testremind(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    await send_lesson_reminders()
    await msg.answer("✅ Напоминания об уроках отправлены!")

@dp.message(Command("testpayment"))
async def cmd_testpayment(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    await send_payment_reminders()
    await msg.answer("✅ Напоминания об оплате отправлены!")

@dp.message(Command("cancel_app"))
async def cmd_cancel_app(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    apps = db.get_new_applications()
    if not apps:
        await msg.answer("📭 Нет активных заявок."); return
    buttons = []
    for app in apps:
        freq = {"2x":"2×/нед","3x":"3×/нед"}.get(app.get("frequency",""),"")
        buttons.append([InlineKeyboardButton(
            text=f"🚫 {app['name']}", callback_data=f"cancelapp_{app['id']}_{app['telegram_id']}_{app.get('lang','ru')}")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="cancelapp_close")])
    await msg.answer("📋 <b>Отменить заявку:</b>", parse_mode="HTML",
                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("cancelapp_"))
async def do_cancel_app(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID: return
    if cb.data == "cancelapp_close":
        await cb.message.edit_text("Закрыто."); await cb.answer(); return
    parts = cb.data.split("_", 3)
    _, app_id, tg_id, lang = parts
    db.update_application(app_id, "cancelled")
    try:
        await bot.send_message(int(tg_id),
            "😔 К сожалению, ваша заявка была отменена." if lang=="ru"
            else "😔 Unfortunately, your application was cancelled.",
            reply_markup=new_user_kb(lang))
    except Exception: pass
    await cb.message.edit_text("✅ Заявка отменена.")
    await cb.answer()

# ── Генерация занятий ─────────────────────────────────────────────────────────

def generate_sessions_with_time(student_id: str, day_times: dict, year: int, month: int) -> list:
    sessions = []
    _, last_day = cal.monthrange(year, month)
    today = today_seoul()
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        dow = str(d.weekday())
        if dow in day_times and d >= today:
            sessions.append({
                "id": str(uuid.uuid4()), "student_id": student_id,
                "date": d.isoformat(), "time": day_times[dow],
                "held": False, "paid": False,
            })
    return sessions

def generate_sessions(student_id: str, day_indices: list, time_str: str, year: int, month: int) -> list:
    sessions = []
    _, last_day = cal.monthrange(year, month)
    today = today_seoul()
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if d.weekday() in day_indices and d >= today:
            sessions.append({
                "id": str(uuid.uuid4()), "student_id": student_id,
                "date": d.isoformat(), "time": time_str, "held": False, "paid": False,
            })
    return sessions

# ── Напоминания ───────────────────────────────────────────────────────────────

async def send_lesson_reminders():
    log.info("Напоминания о занятиях...")
    sessions = db.get_upcoming_sessions(days_ahead=1)
    for s in sessions:
        student = s.get("students")
        if not student or not student.get("telegram_id"): continue
        lang = student.get("telegram_lang","ru")
        day_diff = get_day_diff(s["date"])
        title = get_reminder_title(day_diff, lang)
        if title is None: continue
        d = date.fromisoformat(s["date"])
        date_fmt = fmt_date(d)
        time_str = s.get("time","")
        try:
            await bot.send_message(student["telegram_id"],
                                   t(lang, "reminder_lesson", title=title, date=date_fmt, time=time_str))
        except Exception as e:
            log.warning(f"Ошибка напоминания {student['name']}: {e}")

async def send_payment_reminders():
    log.info("Напоминания об оплате...")
    for s in db.get_students_with_debt():
        if not s.get("telegram_id"): continue
        lang = s.get("telegram_lang","ru")
        fmt = f"{s['debt']:,}".replace(",", " ")
        try:
            await bot.send_message(s["telegram_id"], t(lang, "reminder_payment", amount=fmt))
        except Exception as e:
            log.warning(f"Ошибка оплаты {s['name']}: {e}")

# ── Любое сообщение → показываем меню ────────────────────────────────────────

@dp.message(F.text)
async def handle_any_message(msg: Message, state: FSMContext):
    if msg.from_user.id == TUTOR_ID: return
    current = await state.get_state()
    if current is not None: return
    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        lang = student.get("telegram_lang", lang)
        pending = db.get_pending_application(msg.from_user.id)
        await msg.answer("Выберите действие 👇" if lang=="ru" else "Choose an action 👇",
                         reply_markup=student_kb(lang, has_pending=bool(pending)))
    elif db.get_pending_application(msg.from_user.id):
        pending = db.get_pending_application(msg.from_user.id)
        await msg.answer("⏳ Ваша заявка на рассмотрении." if lang=="ru" else "⏳ Your application is pending.",
                         reply_markup=new_user_kb(lang))
    else:
        await msg.answer(WELCOME_TEXT[lang], reply_markup=new_user_kb(lang))

# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(send_lesson_reminders, "cron", hour=10, minute=0)
    scheduler.add_job(send_payment_reminders, "cron", day_of_week="mon", hour=10, minute=0)
    scheduler.start()
    log.info("Бот запущен!")
    try:
        await bot.send_message(TUTOR_ID, "🤖 Бот запущен!", reply_markup=tutor_kb())
    except Exception: pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
