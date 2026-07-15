"""
Korean Tutor Bot
"""
import asyncio
import logging
from datetime import datetime, date
import calendar
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, TUTOR_ID, TEXTS
import db


# ── Главное меню (кнопки под полем ввода) ────────────────────────────────────

def tutor_menu_kb() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📋 Заявки"),        KeyboardButton(text="👥 Ученики")],
        [KeyboardButton(text="📅 Расписание"),    KeyboardButton(text="💸 Должники")],
        [KeyboardButton(text="📣 Напоминание"),   KeyboardButton(text="❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, persistent=True)

def main_menu_kb(lang: str, has_pending: bool = False) -> ReplyKeyboardMarkup:
    if lang == "ru":
        buttons = [
            [KeyboardButton(text="📝 Записаться на занятия"), KeyboardButton(text="📅 Моё расписание")],
            [KeyboardButton(text="💳 Оплата"),                KeyboardButton(text="❓ Помощь")],
        ]
        if has_pending:
            buttons.append([KeyboardButton(text="🚫 Отозвать заявку")])
    else:
        buttons = [
            [KeyboardButton(text="📝 Apply for lessons"),  KeyboardButton(text="📅 My schedule")],
            [KeyboardButton(text="💳 Payment"),            KeyboardButton(text="❓ Help")],
        ]
        if has_pending:
            buttons.append([KeyboardButton(text="🚫 Cancel application")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, persistent=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── FSM: анкета ученика ───────────────────────────────────────────────────────

class ApplyForm(StatesGroup):
    lang      = State()
    name      = State()
    level     = State()
    frequency = State()
    wishes    = State()  # пожелания по времени (свободный текст)
    username  = State()  # Telegram username
    message   = State()  # доп. сообщение

# ── FSM: подтверждение расписания преподавателем ──────────────────────────────

class RequestLesson(StatesGroup):
    day_select  = State()  # выбор дня недели
    time_input  = State()  # ввод времени
    confirm     = State()  # подтверждение

class RemindForm(StatesGroup):
    type_select   = State()  # урок или оплата
    student_select = State() # выбор ученика

class ConfirmSchedule(StatesGroup):
    select_app  = State()  # выбор заявки
    frequency   = State()  # частота
    days        = State()  # дни недели
    day_times   = State()  # время для каждого дня
    has_free    = State()  # бесплатные занятия
    confirm     = State()  # подтверждение

# ── Вспомогательные функции ───────────────────────────────────────────────────

def get_lang(user) -> str:
    lc = user.language_code or "ru"
    return "en" if not lc.startswith("ru") else "ru"

def t(lang: str, key: str, **kwargs) -> str:
    text = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    return text.format(**kwargs) if kwargs else text

DAYS_RU = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
DAYS_EN = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def days_kb(selected: list) -> InlineKeyboardMarkup:
    """Мультивыбор дней недели для преподавателя"""
    buttons = []
    row = []
    for i, day in enumerate(DAYS_RU):
        check = "✅ " if i in selected else ""
        row.append(InlineKeyboardButton(
            text=f"{check}{day}", callback_data=f"tday_{i}"
        ))
        if len(row) == 4:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✓ Готово", callback_data="tdays_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def generate_sessions_with_time(student_id: str, day_times: dict, year: int, month: int) -> list:
    """Генерирует занятия с временем для каждого дня недели. day_times = {'0': '11:00', '2': '15:00'}"""
    sessions = []
    _, last_day = calendar.monthrange(year, month)
    today = date.today()
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        dow = str(d.weekday())
        if dow in day_times and d >= today:
            sessions.append({
                "id":         str(uuid.uuid4()),
                "student_id": student_id,
                "date":       d.isoformat(),
                "time":       day_times[dow],
                "held":       False,
                "paid":       False,
            })
    return sessions

def generate_sessions(student_id: str, day_indices: list, time_str: str, year: int, month: int) -> list:
    """Генерирует занятия на месяц по дням недели начиная с сегодня"""
    sessions = []
    _, last_day = calendar.monthrange(year, month)
    today = date.today()
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if d.weekday() in day_indices and d >= today:
            sessions.append({
                "id":         str(uuid.uuid4()),
                "student_id": student_id,
                "date":       d.isoformat(),
                "held":       False,
                "paid":       False,
            })
    return sessions

# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)

    # Если пришёл по ссылке ?start=apply — сразу запускаем анкету
    if msg.text and "apply" in msg.text and not student:
        await cmd_apply(msg, state)
        return

    # Преподаватель получает своё меню
    if msg.from_user.id == TUTOR_ID:
        await msg.answer(
            "👩‍🏫 <b>Панель преподавателя</b>",
            reply_markup=tutor_menu_kb(),
            parse_mode="HTML"
        )
        return

    if student:
        await msg.answer(
            f"Добро пожаловать, {student['name']}! 👋",
            reply_markup=main_menu_kb(lang)
        )
    else:
        # Проверяем есть ли активная заявка
        pending = db.get_pending_application(msg.from_user.id)
        has_pending = pending is not None
        hint = ""
        if has_pending:
            hint = "\n\n⏳ Ваша заявка на рассмотрении." if lang=="ru" else "\n\n⏳ Your application is pending."
        elif not student:
            hint = ("\n\n💡 Если вы уже записаны — напишите /link Имя"
                    if lang=="ru" else
                    "\n\n💡 If you are already enrolled — write /link YourName")
        await msg.answer(t(lang, "start") + hint, reply_markup=main_menu_kb(lang, has_pending))

# ── /apply — заявка от ученика ────────────────────────────────────────────────

@dp.message(Command("apply"))
async def cmd_apply(msg: Message, state: FSMContext):
    if db.get_student_by_telegram(msg.from_user.id):
        lang = get_lang(msg.from_user)
        await msg.answer("Вы уже наш ученик! 🎓" if lang=="ru" else "You are already our student! 🎓")
        return
    lang = get_lang(msg.from_user)
    await state.update_data(lang=lang)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇺🇸 English", callback_data="lang_en"),
    ]])
    await msg.answer("Выберите язык / Choose language:", reply_markup=kb)
    await state.set_state(ApplyForm.lang)

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
    ask_un = "Укажите ваш Telegram username (например @username)\nЭто нужно чтобы преподаватель мог написать вам напрямую." if lang=="ru" else "Please share your Telegram username (e.g. @username)\nSo the teacher can contact you directly."
    await msg.answer(ask_un)
    await state.set_state(ApplyForm.username)

@dp.message(ApplyForm.username)
async def apply_username(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    username = msg.text.strip().lstrip('@') if msg.text.strip() not in ('-','нет','no','—') else None
    await state.update_data(username=username)
    await msg.answer(t(lang, "ask_message"))
    await state.set_state(ApplyForm.message)

@dp.message(ApplyForm.message)
async def apply_done(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    # Берём username из Telegram если не указал вручную
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
    await msg.answer(t(lang, "applied"), reply_markup=main_menu_kb(lang, has_pending=True))

    freq_label = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(data.get("frequency",""),"")
    tg_username = data.get('username') or msg.from_user.username
    username_line = f"@{tg_username}" if tg_username else f"ID: {msg.from_user.id}"
    notif = (
        f"📬 <b>Новая заявка!</b>\n\n"
        f"👤 {data['name']}\n"
        f"📊 Уровень: {data.get('level','—')}\n"
        f"📅 Желаемая частота: {freq_label}\n"
        f"⏰ Пожелания по времени: {data.get('wishes','—')}\n"
        f"💬 {msg.text}\n"
        f"🌐 {'🇷🇺' if lang=='ru' else '🇺🇸'}\n"
        f"✉️ Контакт: {username_line}\n\n"
        f"Когда договоритесь о расписании — используй /schedule_set"
    )
    # Кнопка «Написать» если есть username
    kb = None
    if tg_username:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✉️ Написать @{tg_username}", url=f"https://t.me/{tg_username}")
        ]])
    await bot.send_message(TUTOR_ID, notif, parse_mode="HTML", reply_markup=kb)
    await state.clear()

# ── /schedule_set — преподаватель утверждает расписание ───────────────────────

@dp.message(Command("schedule_set"))
async def cmd_schedule_set(msg: Message, state: FSMContext):
    if msg.from_user.id != TUTOR_ID:
        return

    # Показываем список новых заявок
    apps = db.get_new_applications()
    if not apps:
        await msg.answer(
            "📭 Нет новых заявок.\n\n"
            "Если ученик уже есть в системе и нужно добавить занятия — "
            "используй /add_sessions"
        )
        return

    buttons = []
    for app in apps:
        freq = {"2x":"2×/нед","3x":"3×/нед"}.get(app.get("frequency",""),"")
        buttons.append([InlineKeyboardButton(
            text=f"👤 {app['name']} ({freq})",
            callback_data=f"pickapp_{app['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_sched")])

    await msg.answer(
        "📋 <b>Выбери заявку для утверждения расписания:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await state.set_state(ConfirmSchedule.select_app)

@dp.callback_query(ConfirmSchedule.select_app, F.data.startswith("pickapp_"))
async def pick_application(cb: CallbackQuery, state: FSMContext):
    app_id = cb.data.replace("pickapp_", "")
    app = db.get_application(app_id)
    if not app:
        await cb.answer("Заявка не найдена", show_alert=True); return

    await state.update_data(app_id=app_id, app=app, selected_days=[])

    # Показываем данные заявки
    freq = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(app.get("frequency",""),"")
    await cb.message.edit_text(
        f"👤 <b>{app['name']}</b>\n"
        f"📊 {app.get('level','—')} · {freq}\n"
        f"⏰ Пожелания: {app.get('preferred_time','—')}\n\n"
        f"Выбери <b>частоту занятий</b>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="2 раза в неделю", callback_data="tfreq_2x"),
            InlineKeyboardButton(text="3 раза в неделю", callback_data="tfreq_3x"),
        ]])
    )
    await state.set_state(ConfirmSchedule.frequency)
    await cb.answer()

@dp.callback_query(ConfirmSchedule.select_app, F.data == "cancel_sched")
async def cancel_sched(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")
    await cb.answer()

@dp.callback_query(ConfirmSchedule.frequency, F.data.startswith("tfreq_"))
async def confirm_freq(cb: CallbackQuery, state: FSMContext):
    freq = cb.data.replace("tfreq_", "")
    await state.update_data(frequency=freq, selected_days=[])
    await cb.message.edit_text(
        "📆 <b>Выбери дни недели</b> (можно несколько):",
        parse_mode="HTML",
        reply_markup=days_kb([])
    )
    await state.set_state(ConfirmSchedule.days)
    await cb.answer()

@dp.callback_query(ConfirmSchedule.days, F.data.startswith("tday_"))
async def toggle_day(cb: CallbackQuery, state: FSMContext):
    idx = int(cb.data.replace("tday_", ""))
    data = await state.get_data()
    selected = data.get("selected_days", [])
    if idx in selected: selected.remove(idx)
    else: selected.append(idx)
    await state.update_data(selected_days=selected)
    await cb.message.edit_reply_markup(reply_markup=days_kb(selected))
    await cb.answer()

@dp.callback_query(ConfirmSchedule.days, F.data == "tdays_done")
async def days_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = sorted(data.get("selected_days", []))
    if not selected:
        await cb.answer("Выбери хотя бы один день!", show_alert=True); return
    # Начинаем спрашивать время для первого дня
    await state.update_data(selected_days=selected, day_times={}, time_day_idx=0)
    first_day = DAYS_RU[selected[0]]
    await cb.message.edit_text(
        f"⏰ <b>Время для {first_day}?</b>\n\nНапример: <code>11:00</code>",
        parse_mode="HTML"
    )
    await state.set_state(ConfirmSchedule.day_times)
    await cb.answer()



@dp.message(ConfirmSchedule.day_times)
async def confirm_day_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    selected = data["selected_days"]
    day_times = data.get("day_times", {})
    idx = data.get("time_day_idx", 0)

    # Сохраняем время для текущего дня
    time_input = msg.text.strip()
    day_times[str(selected[idx])] = time_input
    await state.update_data(day_times=day_times)

    # Переходим к следующему дню
    next_idx = idx + 1
    if next_idx < len(selected):
        await state.update_data(time_day_idx=next_idx)
        next_day = DAYS_RU[selected[next_idx]]
        await msg.answer(
            f"⏰ <b>Время для {next_day}?</b>\n\nНапример: <code>15:00</code>",
            parse_mode="HTML"
        )
    else:
        # Все дни заполнены — спрашиваем бесплатные занятия
        await state.update_data(time_day_idx=0)
        await msg.answer(
            "🎁 <b>Бесплатные занятия?</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Да, 8 занятий", callback_data="free_yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data="free_no"),
            ]])
        )
        await state.set_state(ConfirmSchedule.has_free)

@dp.callback_query(ConfirmSchedule.has_free, F.data.startswith("free_"))
async def confirm_free(cb: CallbackQuery, state: FSMContext):
    has_free = cb.data == "free_yes"
    await state.update_data(has_free=has_free)
    data = await state.get_data()
    app = data["app"]

    days_label = ", ".join(DAYS_RU[i] for i in sorted(data["selected_days"]))
    freq_label = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(data["frequency"],"")

    today = date.today()
    sessions = generate_sessions(
        "PREVIEW", data["selected_days"], data.get("time_slot",""), today.year, today.month
    )
    # Следующий месяц если осталось < 2 недель
    import calendar as cal
    days_left = (date(today.year, today.month, cal.monthrange(today.year, today.month)[1]) - today).days
    if days_left < 14:
        nm = today.month+1 if today.month<12 else 1
        ny = today.year if today.month<12 else today.year+1
        sessions += generate_sessions("PREVIEW", data["selected_days"], data.get("time_slot",""), ny, nm)

    await cb.message.edit_text(
        f"📋 <b>Подтверди расписание:</b>\n\n"
        f"👤 {app['name']} · {app.get('level','')}\n"
        f"📅 {freq_label} · {days_label}\n"
        f"⏰ Время: {data.get('time_slot','—')}\n"
        f"🎁 Бесплатных: {'8 занятий' if has_free else 'нет'}\n"
        f"📆 Будет создано занятий: <b>{len(sessions)}</b>\n\n"
        f"Всё верно?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="sched_confirm"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="sched_restart"),
        ]])
    )
    await state.set_state(ConfirmSchedule.confirm)
    await cb.answer()

@dp.callback_query(ConfirmSchedule.confirm, F.data == "sched_restart")
async def sched_restart(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(selected_days=[])
    await cb.message.edit_text(
        "📆 <b>Выбери дни недели заново:</b>",
        parse_mode="HTML",
        reply_markup=days_kb([])
    )
    await state.set_state(ConfirmSchedule.days)
    await cb.answer()

@dp.callback_query(ConfirmSchedule.confirm, F.data == "sched_confirm")
async def sched_confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    app  = data["app"]

    # 1. Создаём ученика
    student = db.create_student({
        "name":          app["name"],
        "level":         app.get("level",""),
        "start_date":    date.today().isoformat(),
        "has_free":      data["has_free"],
        "free_count":    8 if data["has_free"] else 0,
        "frequency":     data["frequency"],
        "payment_type":  "perSession",
        "notes":         app.get("message") or "",
        "telegram_id":   app["telegram_id"],
        "telegram_lang": app.get("lang","ru"),
    })

    # 2. Генерируем занятия
    today = date.today()
    import calendar as cal
    sessions = generate_sessions(
        student["id"], data["selected_days"], data.get("time_slot",""), today.year, today.month
    )
    days_left = (date(today.year, today.month, cal.monthrange(today.year, today.month)[1]) - today).days
    if days_left < 14:
        nm = today.month+1 if today.month<12 else 1
        ny = today.year if today.month<12 else today.year+1
        sessions += generate_sessions(student["id"], data["selected_days"], data.get("time_slot",""), ny, nm)

    for s in sessions:
        db.add_session_direct(s)

    # 3. Закрываем заявку
    db.update_application(data["app_id"], "approved")

    days_label = ", ".join(DAYS_RU[i] for i in sorted(data["selected_days"]))
    freq_label = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(data["frequency"],"")

    await cb.message.edit_text(
        f"✅ <b>Готово!</b>\n\n"
        f"👤 {app['name']} добавлен в систему\n"
        f"📅 {freq_label} · {days_label} · {data.get('time_slot','')}\n"
        f"📆 Создано занятий: <b>{len(sessions)}</b>\n\n"
        f"Занятия уже отображаются в системе! 🎉",
        parse_mode="HTML"
    )

    # 4. Уведомляем ученика
    lang = app.get("lang","ru")
    await bot.send_message(app["telegram_id"], t(lang, "approved"))
    await state.clear()
    await cb.answer()


# ── /link — привязка существующего ученика ───────────────────────────────────

@dp.message(Command("link"))
async def cmd_link(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        lang = student.get("telegram_lang", "ru")
        await msg.answer(
            f"Вы уже привязаны как {student['name']} ✅" if lang=="ru"
            else f"You are already linked as {student['name']} ✅"
        )
        return

    # Ищем по имени — ученик должен написать /link Имя
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(
            "Напишите команду с вашим именем:\n"
            "<code>/link Екатерина</code> или <code>/link Александр</code>\n\n"
            "Имя должно совпадать с тем, что вы указали при записи.",
            parse_mode="HTML"
        )
        return

    search_name = parts[1].strip().lower()
    all_students = db.get_all_students()

    # Ищем совпадение по имени (частичное)
    found = [s for s in all_students if search_name in s["name"].lower()]

    if not found:
        await msg.answer(
            f"Ученик с именем <b>{parts[1]}</b> не найден.\n\n"
            f"Проверьте написание имени или подайте заявку: /apply",
            parse_mode="HTML"
        )
        return

    if len(found) > 1:
        names = "\n".join(f"• {s['name']}" for s in found)
        await msg.answer(
            f"Найдено несколько совпадений:\n{names}\n\n"
            f"Уточните полное имя, например:\n<code>/link Дьяченко Екатерина</code>",
            parse_mode="HTML"
        )
        return

    # Нашли одного — привязываем
    student = found[0]
    username = msg.from_user.username
    db.update_student(student["id"], {
        "telegram_id":   msg.from_user.id,
        "telegram_lang": "ru",
        "username":      username or "",
    })

    lang_student = student.get("telegram_lang", "ru")
    await msg.answer(
        f"✅ Готово! Вы привязаны как <b>{student['name']}</b>\n\n"
        f"{'Теперь вам доступны все функции бота 👇' if lang_student=='ru' else 'You now have access to all bot features 👇'}",
        parse_mode="HTML",
        reply_markup=main_menu_kb(lang_student)
    )

    # Уведомляем преподавателя
    await bot.send_message(
        TUTOR_ID,
        f"🔗 <b>Ученик привязал аккаунт</b>\n\n"
        f"👤 {student['name']}\n"
        f"✉️ {'@' + username if username else 'без username'}\n"
        f"🆔 <code>{msg.from_user.id}</code>",
        parse_mode="HTML"
    )



# ── Запрос разового занятия существующим учеником ────────────────────────────

async def request_lesson_start(msg: Message, state: FSMContext, student: dict, lang: str):
    """Начало флоу запроса разового занятия"""
    text_ru = (
        "📅 Укажите удобное время для занятия.\n\n"
        "Сначала выберите день недели:"
    )
    text_en = (
        "📅 Please indicate a convenient time for the lesson.\n\n"
        "First, select the day of the week:"
    )

    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days = days_ru if lang == "ru" else days_en

    buttons = []
    row = []
    for i, day in enumerate(days):
        row.append(InlineKeyboardButton(text=day, callback_data=f"rlesson_day_{i}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)

    await state.update_data(student_id=student["id"], student_name=student["name"], lang=lang)
    await msg.answer(
        text_ru if lang == "ru" else text_en,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(RequestLesson.day_select)

@dp.callback_query(RequestLesson.day_select, F.data.startswith("rlesson_day_"))
async def request_lesson_day(cb: CallbackQuery, state: FSMContext):
    dow = int(cb.data.replace("rlesson_day_", ""))
    data = await state.get_data()
    lang = data["lang"]
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = days_ru[dow] if lang == "ru" else days_en[dow]

    await state.update_data(dow=dow, day_name=day_name)
    text_ru = f"✅ {day_name}\n\nТеперь укажите удобное время.\nНапример: <code>15:00</code>"
    text_en = f"✅ {day_name}\n\nNow enter a convenient time.\nFor example: <code>15:00</code>"
    await cb.message.edit_text(
        text_ru if lang == "ru" else text_en,
        parse_mode="HTML"
    )
    await state.set_state(RequestLesson.time_input)
    await cb.answer()

@dp.message(RequestLesson.time_input)
async def request_lesson_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    time_text = msg.text.strip()

    await state.update_data(time_text=time_text)

    day_name = data["day_name"]
    text_ru = (
        f"📋 Проверьте запрос:\n\n"
        f"📅 День: {day_name}\n"
        f"⏰ Время: {time_text}\n\n"
        f"Отправить запрос преподавателю?"
    )
    text_en = (
        f"📋 Check your request:\n\n"
        f"📅 Day: {day_name}\n"
        f"⏰ Time: {time_text}\n\n"
        f"Send request to the teacher?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Отправить" if lang=="ru" else "✅ Send",
            callback_data="rlesson_confirm"
        ),
        InlineKeyboardButton(
            text="✏️ Изменить" if lang=="ru" else "✏️ Edit",
            callback_data="rlesson_edit"
        ),
    ]])
    await msg.answer(text_ru if lang=="ru" else text_en, reply_markup=kb, parse_mode="HTML")
    await state.set_state(RequestLesson.confirm)

@dp.callback_query(RequestLesson.confirm, F.data == "rlesson_edit")
async def request_lesson_edit(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await cb.message.edit_text(
        "⏰ Введите время заново. Например: <code>15:00</code>" if lang=="ru"
        else "⏰ Enter time again. For example: <code>15:00</code>",
        parse_mode="HTML"
    )
    await state.set_state(RequestLesson.time_input)
    await cb.answer()

@dp.callback_query(RequestLesson.confirm, F.data == "rlesson_confirm")
async def request_lesson_send(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    student_id = data["student_id"]
    student_name = data["student_name"]
    day_name = data["day_name"]
    time_text = data["time_text"]
    dow = data["dow"]

    # Подтверждение ученику
    text_ru = (
        "✅ Запрос отправлен!\n\n"
        "Преподаватель рассмотрит и утвердит занятие.\n"
        "Вы получите уведомление."
    )
    text_en = (
        "✅ Request sent!\n\n"
        "The teacher will review and confirm the lesson.\n"
        "You will receive a notification."
    )
    await cb.message.edit_text(text_ru if lang=="ru" else text_en)

    # Уведомление преподавателю с кнопкой утверждения
    notif = (
        f"📬 <b>Запрос на занятие от ученика!</b>\n\n"
        f"👤 {student_name}\n"
        f"📅 День: {day_name}\n"
        f"⏰ Время: {time_text}\n"
        f"🆔 student_id: <code>{student_id}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Утвердить занятие",
            callback_data=f"approve_lesson_{student_id}_{dow}_{time_text}_{cb.from_user.id}_{lang}"
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"reject_lesson_{cb.from_user.id}_{lang}"
        ),
    ]])
    await bot.send_message(TUTOR_ID, notif, parse_mode="HTML", reply_markup=kb)
    await state.clear()
    await cb.answer()

@dp.callback_query(F.data.startswith("approve_lesson_"))
async def approve_lesson_request(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID: return
    # approve_lesson_{student_id}_{dow}_{time}_{student_tg_id}_{lang}
    parts = cb.data.split("_")
    # approve lesson {student_id} {dow} {time} {tg_id} {lang}
    student_id  = parts[2]
    dow         = int(parts[3])
    time_text   = parts[4]
    student_tg_id = int(parts[5])
    lang        = parts[6] if len(parts) > 6 else "ru"

    # Находим ближайшую дату с этим днём недели
    from datetime import date, timedelta
    today = date.today()
    days_ahead = (dow - today.weekday()) % 7
    if days_ahead == 0: days_ahead = 7  # если сегодня — берём следующую неделю
    lesson_date = (today + timedelta(days=days_ahead)).isoformat()

    # Добавляем занятие в Supabase
    import uuid as _uuid
    session = {
        "id":         str(_uuid.uuid4()),
        "student_id": student_id,
        "date":       lesson_date,
        "time":       time_text,
        "held":       False,
        "paid":       False,
    }
    db.add_session_direct(session)

    # Обновляем сообщение преподавателю
    days_ru = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    await cb.message.edit_text(
        f"✅ <b>Занятие утверждено!</b>\n\n"
        f"📅 {days_ru[dow]}, {lesson_date}\n"
        f"⏰ {time_text}\n\n"
        f"Занятие добавлено в систему.",
        parse_mode="HTML"
    )

    # Уведомление ученику
    from datetime import datetime
    date_fmt = datetime.fromisoformat(lesson_date).strftime("%d.%m.%Y")
    days_names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    days_en = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    day_name = days_names[dow] if lang=="ru" else days_en[dow]

    text_ru = (
        f"🎉 Занятие утверждено!\n\n"
        f"📅 {day_name}, {date_fmt}\n"
        f"⏰ {time_text}\n\n"
        f"До встречи! 💪"
    )
    text_en = (
        f"🎉 Lesson confirmed!\n\n"
        f"📅 {day_name}, {date_fmt}\n"
        f"⏰ {time_text}\n\n"
        f"See you! 💪"
    )
    try:
        await bot.send_message(student_tg_id, text_ru if lang=="ru" else text_en)
    except Exception as e:
        log.warning(f"Не удалось уведомить ученика: {e}")
    await cb.answer()

@dp.callback_query(F.data.startswith("reject_lesson_"))
async def reject_lesson_request(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID: return
    parts = cb.data.split("_")
    student_tg_id = int(parts[2])
    lang = parts[3] if len(parts) > 3 else "ru"

    await cb.message.edit_text("❌ Запрос на занятие отклонён.")

    text_ru = "😔 К сожалению, преподаватель не может провести занятие в указанное время.\n\nПопробуйте выбрать другое время."
    text_en = "😔 Unfortunately, the teacher is not available at the requested time.\n\nPlease try a different time."
    try:
        await bot.send_message(student_tg_id, text_ru if lang=="ru" else text_en)
    except Exception as e:
        log.warning(f"Не удалось уведомить ученика: {e}")
    await cb.answer()

# ── /schedule — расписание ученика ────────────────────────────────────────────

@dp.message(Command("schedule"))
async def cmd_schedule(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы. Подайте заявку: /apply"); return
    lang = student.get("telegram_lang","ru")
    sessions = db.get_sessions_for_student(student["id"])
    upcoming = [s for s in sessions if s["date"] >= date.today().isoformat() and not s["held"]]
    if not upcoming:
        await msg.answer("📅 Ближайших занятий нет." if lang=="ru" else "📅 No upcoming lessons."); return
    try:
        sched = db.get_student_schedule(student["id"])
    except Exception:
        sched = []

    lines = ["📅 <b>Ваше расписание:</b>\n" if lang=="ru" else "📅 <b>Your schedule:</b>\n"]
    if sched:
        for row in sched:
            lines.append(f"  {DAYS_RU[row['dow']]} — {row['time']}")
        lines.append("")

    lines.append("<b>Ближайшие занятия:</b>" if lang=="ru" else "<b>Upcoming lessons:</b>")
    for s in upcoming[:5]:
        d = datetime.fromisoformat(s['date']).strftime('%d.%m')
        dow = DAYS_RU[(datetime.fromisoformat(s['date']).weekday())]
        time_str = f" в {s['time']}" if s.get('time') else ""
        lines.append(f"• {dow} {d}{time_str}")
    await msg.answer("\n".join(lines), parse_mode="HTML")

# ── /payment ──────────────────────────────────────────────────────────────────

@dp.message(Command("payment"))
async def cmd_payment(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы. Подайте заявку: /apply"); return
    lang = student.get("telegram_lang","ru")
    debt = db.get_student_debt(student["id"])
    if debt == 0:
        await msg.answer("✅ Оплата в порядке!" if lang=="ru" else "✅ All paid!")
    else:
        fmt = f"{debt:,}".replace(",", " ")
        text = (f"💳 Задолженность: <b>{fmt} ₩</b>\n\nПожалуйста, оплатите при возможности."
                if lang=="ru" else f"💳 Balance: <b>{fmt} ₩</b>\n\nPlease pay when you can.")
        await msg.answer(text, parse_mode="HTML")

# ── Команды преподавателя ─────────────────────────────────────────────────────

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

@dp.message(Command("students"))
async def cmd_students(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    students = db.get_all_students()
    if not students:
        await msg.answer("Учеников нет."); return
    lines = [f"👥 <b>Ученики ({len(students)}):</b>\n"]
    for s in students:
        freq = {"2x":"2×/нед","3x":"3×/нед"}.get(s["frequency"],"")
        tg = f" ✅" if s.get("telegram_id") else " (не в боте)"
        lines.append(f"• {s['name']} — {freq}{tg}")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@dp.message(Command("testremind"))
async def cmd_testremind(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    await send_lesson_reminders()
    await msg.answer("✅ Напоминания о занятиях отправлены!")

@dp.message(Command("testpayment"))
async def cmd_testpayment(msg: Message):
    if msg.from_user.id != TUTOR_ID: return
    await send_payment_reminders()
    await msg.answer("✅ Напоминания об оплате отправлены!")

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    if msg.from_user.id == TUTOR_ID:
        await msg.answer(
            "👩‍🏫 <b>Команды преподавателя:</b>\n\n"
            "/schedule_set — утвердить расписание с учеником\n"
            "/remind — отправить напоминание (урок или оплата)\n"
            "/students — список всех учеников\n"
            "/debtors — должники\n"
            "/testremind — авто-напоминания об уроках\n"
            "/testpayment — авто-напоминания об оплате",
            parse_mode="HTML"
        )
    else:
        lang = get_lang(msg.from_user)
        await msg.answer(t(lang, "start"))



# ── Кнопки преподавателя ─────────────────────────────────────────────────────

@dp.message(F.text.in_({
    "📋 Заявки", "👥 Ученики", "📅 Расписание",
    "💸 Должники", "📣 Напоминание", "❓ Помощь",
}))
async def handle_tutor_buttons(msg: Message, state: FSMContext):
    if msg.from_user.id != TUTOR_ID: return
    text = msg.text

    if text == "📋 Заявки":
        await cmd_cancel_app(msg)

    elif text == "👥 Ученики":
        await cmd_students(msg)

    elif text == "📅 Расписание":
        await cmd_schedule_set(msg, state)

    elif text == "💸 Должники":
        await cmd_debtors(msg)

    elif text == "📣 Напоминание":
        await cmd_remind(msg, state)

    elif text == "❓ Помощь":
        await msg.answer(
            "👩‍🏫 <b>Команды преподавателя:</b>\n\n"
            "/schedule_set — утвердить расписание\n"
            "/remind — отправить напоминание\n"
            "/students — все ученики\n"
            "/debtors — должники",
            parse_mode="HTML",
            reply_markup=tutor_menu_kb()
        )


# ── Отзыв заявки учеником ────────────────────────────────────────────────────

@dp.message(F.text.in_({"🚫 Отозвать заявку", "🚫 Cancel application"}))
async def cancel_own_application(msg: Message):
    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        await msg.answer(
            "Вы уже являетесь нашим учеником — отзывать нечего." if lang=="ru"
            else "You are already our student — nothing to cancel."
        )
        return

    pending = db.get_pending_application(msg.from_user.id)
    if not pending:
        await msg.answer(
            "У вас нет активных заявок." if lang=="ru"
            else "You have no active applications."
        )
        return

    db.update_application(pending["id"], "cancelled")

    await msg.answer(
        "🚫 Заявка отозвана.\n\nВы можете подать новую заявку в любое время." if lang=="ru"
        else "🚫 Application cancelled.\n\nYou can apply again at any time.",
        reply_markup=main_menu_kb(lang, has_pending=False)
    )

    # Уведомляем преподавателя
    await bot.send_message(
        TUTOR_ID,
        f"🚫 <b>Ученик отозвал заявку</b>\n\n"
        f"👤 {pending['name']}\n"
        f"🆔 <code>{msg.from_user.id}</code>",
        parse_mode="HTML"
    )

# ── Обработчик кнопок главного меню ──────────────────────────────────────────

@dp.message(F.text.in_({
    "📝 Записаться на занятия", "📝 Apply for lessons",
    "📅 Моё расписание",        "📅 My schedule",
    "💳 Оплата",                "💳 Payment",
    "❓ Помощь",                "❓ Help",
}))
async def handle_menu_buttons(msg: Message, state: FSMContext):
    text = msg.text

    if text in ("📝 Записаться на занятия", "📝 Apply for lessons"):
        await cmd_apply(msg, state)

    elif text in ("📅 Моё расписание", "📅 My schedule"):
        await cmd_schedule(msg)

    elif text in ("💳 Оплата", "💳 Payment"):
        await cmd_payment(msg)

    elif text in ("🚫 Отозвать заявку", "🚫 Cancel application"):
        await cancel_own_application(msg)

    elif text in ("❓ Помощь", "❓ Help"):
        await cmd_help(msg)


# ── /remind — ручная отправка напоминаний ────────────────────────────────────

@dp.message(Command("remind"))
async def cmd_remind(msg: Message, state: FSMContext):
    if msg.from_user.id != TUTOR_ID: return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Напомнить об уроке",   callback_data="remind_lesson")],
        [InlineKeyboardButton(text="💳 Напомнить об оплате",  callback_data="remind_payment")],
        [InlineKeyboardButton(text="📚💳 Всем об уроке",      callback_data="remind_lesson_all")],
        [InlineKeyboardButton(text="💳📢 Всем должникам",     callback_data="remind_payment_all")],
    ])
    await msg.answer("📣 <b>Что напомнить?</b>", parse_mode="HTML", reply_markup=kb)
    await state.set_state(RemindForm.type_select)

@dp.callback_query(RemindForm.type_select, F.data.startswith("remind_"))
async def remind_type(cb: CallbackQuery, state: FSMContext):
    rtype = cb.data  # remind_lesson / remind_payment / remind_lesson_all / remind_payment_all

    if rtype == "remind_lesson_all":
        await cb.message.edit_text("⏳ Отправляю напоминания об уроках...")
        await send_lesson_reminders()
        await cb.message.edit_text("✅ Напоминания об уроках отправлены всем!")
        await state.clear(); await cb.answer(); return

    if rtype == "remind_payment_all":
        await cb.message.edit_text("⏳ Отправляю напоминания об оплате...")
        await send_payment_reminders()
        await cb.message.edit_text("✅ Напоминания об оплате отправлены всем должникам!")
        await state.clear(); await cb.answer(); return

    # Выбор конкретного ученика
    students = db.get_all_students()
    with_tg  = [s for s in students if s.get("telegram_id")]

    if not with_tg:
        await cb.message.edit_text("😔 Нет учеников с привязанным Telegram аккаунтом.")
        await state.clear(); await cb.answer(); return

    await state.update_data(rtype=rtype)

    buttons = []
    for s in with_tg:
        label = f"👤 {s['name']}"
        if rtype == "remind_payment":
            debt = db.get_student_debt(s["id"])
            if debt == 0:
                label += " ✅ (нет долга)"
            else:
                fmt = f"{debt:,}".replace(",", " ")
                label += f" — {fmt} ₩"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"rpick_{s['id']}")])

    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="remind_cancel")])

    title = "📚 Кому напомнить об уроке?" if rtype == "remind_lesson" else "💳 Кому напомнить об оплате?"
    await cb.message.edit_text(f"<b>{title}</b>", parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(RemindForm.student_select)
    await cb.answer()

@dp.callback_query(RemindForm.student_select, F.data == "remind_cancel")
async def remind_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")
    await cb.answer()

@dp.callback_query(RemindForm.student_select, F.data.startswith("rpick_"))
async def remind_send(cb: CallbackQuery, state: FSMContext):
    student_id = cb.data.replace("rpick_", "")
    data  = await state.get_data()
    rtype = data.get("rtype")

    student = next((s for s in db.get_all_students() if s["id"] == student_id), None)
    if not student or not student.get("telegram_id"):
        await cb.answer("Ученик не найден или нет Telegram", show_alert=True)
        await state.clear(); return

    lang = student.get("telegram_lang", "ru")

    if rtype == "remind_lesson":
        # Ближайшее занятие
        sessions = db.get_sessions_for_student(student_id)
        upcoming = [s for s in sessions if s["date"] >= date.today().isoformat() and not s["held"]]

        if not upcoming:
            await cb.message.edit_text(f"😔 У {student['name']} нет предстоящих занятий.")
            await state.clear(); await cb.answer(); return

        next_s = upcoming[0]
        d = datetime.fromisoformat(next_s["date"]).strftime("%d.%m.%Y")
        time_str = f" в {next_s['time']}" if next_s.get("time") else ""

        day_diff = get_calendar_day_diff(next_s["date"])
        title_ru = get_reminder_title(day_diff, "ru")
        title_en = get_reminder_title(day_diff, "en")
        if title_ru is None:
            await cb.message.edit_text(
                f"\u26a0\ufe0f Нельзя отправить напоминание: дата занятия уже прошла.\n\n"
                f"\U0001F464 {student['name']}\n\U0001F4C5 {d}"
            )
            await state.clear(); await cb.answer(); return
        msg_lesson_ru = (
            f"\U0001F4DA {title_ru} по корейскому.\n"
            f"\U0001F4C5 {d}{time_str}\n\n"
            "До встречи! \U0001F4AA"
        )
        msg_lesson_en = (
            f"\U0001F4DA {title_en}.\n"
            f"\U0001F4C5 {d}{time_str}\n\n"
            "See you! \U0001F4AA"
        )
        text = msg_lesson_ru if lang == "ru" else msg_lesson_en

        await bot.send_message(student["telegram_id"], text)
        await cb.message.edit_text(
            f"\u2705 Напоминание об уроке отправлено!\n\n"
            f"\U0001F464 {student['name']}\n\U0001F4C5 {d}{time_str}"
        )

    elif rtype == "remind_payment":
        debt = db.get_student_debt(student_id)
        if debt == 0:
            await cb.message.edit_text(f"✅ У {student['name']} нет долгов — напоминание не нужно.")
            await state.clear(); await cb.answer(); return

        fmt = f"{debt:,}".replace(",", " ")
        day_diff = get_calendar_day_diff(next_s["date"])
        title_ru = get_reminder_title(day_diff, "ru")
        title_en = get_reminder_title(day_diff, "en")
        if title_ru is None:
            await cb.message.edit_text(
                f"\u26a0\ufe0f Нельзя отправить напоминание: дата занятия уже прошла.\n\n"
                f"\U0001F464 {student['name']}\n\U0001F4C5 {d}"
            )
            await state.clear(); await cb.answer(); return
        msg_lesson_ru = (
            f"\U0001F4DA {title_ru} по корейскому.\n"
            f"\U0001F4C5 {d}{time_str}\n\n"
            "До встречи! \U0001F4AA"
        )
        msg_lesson_en = (
            f"\U0001F4DA {title_en}.\n"
            f"\U0001F4C5 {d}{time_str}\n\n"
            "See you! \U0001F4AA"
        )
        text = msg_lesson_ru if lang == "ru" else msg_lesson_en

        await bot.send_message(student["telegram_id"], text)
        await cb.message.edit_text(
            f"\u2705 Напоминание об оплате отправлено!\n\n"
            f"\U0001F464 {student['name']}\n\U0001F4B3 {fmt} \u20a9"
        )

    await state.clear()
    await cb.answer()


# ── /cancel_app — отмена заявок преподавателем ───────────────────────────────

@dp.message(Command("cancel_app"))
async def cmd_cancel_app(msg: Message):
    if msg.from_user.id != TUTOR_ID: return

    apps = db.get_new_applications()
    if not apps:
        await msg.answer("📭 Нет активных заявок.")
        return

    buttons = []
    for app in apps:
        freq = {"2x":"2×/нед","3x":"3×/нед"}.get(app.get("frequency",""),"")
        buttons.append([InlineKeyboardButton(
            text=f"🚫 {app['name']} ({freq})",
            callback_data=f"cancelapp_{app['id']}_{app['telegram_id']}_{app.get('lang','ru')}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="cancelapp_close")])

    await msg.answer(
        "📋 <b>Активные заявки — выбери какую отменить:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("cancelapp_"))
async def do_cancel_app(cb: CallbackQuery):
    if cb.from_user.id != TUTOR_ID: return

    if cb.data == "cancelapp_close":
        await cb.message.edit_text("Закрыто.")
        await cb.answer(); return

    parts = cb.data.split("_", 3)
    _, app_id, tg_id, lang = parts

    db.update_application(app_id, "cancelled")

    # Уведомляем ученика
    text_ru = "😔 К сожалению, ваша заявка была отменена.\n\nВы можете подать новую заявку в любое время."
    text_en = "😔 Unfortunately, your application was cancelled.\n\nYou can apply again at any time."
    try:
        await bot.send_message(
            int(tg_id),
            text_ru if lang == "ru" else text_en,
            reply_markup=main_menu_kb(lang, has_pending=False)
        )
    except Exception:
        pass

    await cb.message.edit_text(f"✅ Заявка отменена. Ученик уведомлён.")
    await cb.answer()

# ── Напоминания ─────────────────────────────────────────────────────────────

# ── Вспомогательные функции для дат (Asia/Seoul) ─────────────────────────────

def get_today_seoul() -> str:
    """Сегодняшняя дата в Asia/Seoul в формате YYYY-MM-DD"""
    from datetime import timezone
    import zoneinfo
    try:
        tz = zoneinfo.ZoneInfo("Asia/Seoul")
    except Exception:
        # fallback: UTC+9
        from datetime import timedelta as td
        return (date.today() + td(hours=9)).isoformat()[:10]
    from datetime import datetime as dt
    return dt.now(tz).strftime("%Y-%m-%d")

def get_calendar_day_diff(lesson_date_str: str) -> int:
    """Разница в календарных днях между сегодня (Seoul) и датой занятия.
    Положительное = будущее, 0 = сегодня, отрицательное = прошлое."""
    today_str = get_today_seoul()
    today_d = date.fromisoformat(today_str)
    lesson_d = date.fromisoformat(lesson_date_str[:10])
    return (lesson_d - today_d).days

def pluralize_days(n: int) -> str:
    """Правильное склонение слова 'день' для русского языка"""
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return "день"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "дня"
    return "дней"

def get_reminder_title(day_diff: int, lang: str) -> str | None:
    """Возвращает заголовок напоминания в зависимости от разницы дней.
    None если занятие в прошлом."""
    if day_diff < 0:
        return None  # прошлое — не отправляем
    if lang == "ru":
        if day_diff == 0: return "Сегодня у вас занятие"
        if day_diff == 1: return "Завтра у вас занятие"
        if day_diff == 2: return "Через два дня у вас занятие"
        return f"У вас занятие через {day_diff} {pluralize_days(day_diff)}"
    else:
        if day_diff == 0: return "You have a lesson today"
        if day_diff == 1: return "You have a lesson tomorrow"
        if day_diff == 2: return "You have a lesson in two days"
        return f"You have a lesson in {day_diff} days"

def format_lesson_date(date_str: str) -> str:
    """Форматирует дату занятия для вывода: 17.07.2026"""
    return datetime.fromisoformat(date_str[:10]).strftime("%d.%m.%Y")


async def send_lesson_reminders():
    log.info("Напоминания о занятиях...")
    sessions = db.get_upcoming_sessions(days_ahead=1)  # сегодня + завтра
    for s in sessions:
        student = s.get("students")
        if not student or not student.get("telegram_id"): continue
        if s.get("held"): continue  # уже проведено — пропускаем
        lang = student.get("telegram_lang", "ru")
        date_str = s["date"][:10]
        day_diff = get_calendar_day_diff(date_str)
        title = get_reminder_title(day_diff, lang)
        if title is None:
            log.info(f"Занятие {date_str} уже прошло — пропускаем")
            continue
        date_fmt = format_lesson_date(date_str)
        time_str = f" — {s['time']}" if s.get("time") else ""
        if lang == "ru":
            text = (
                f"\U0001F4DA {title} по корейскому.\n"
                f"\U0001F4C5 {date_fmt}{time_str}\n\n"
                "До встречи! \U0001F4AA"
            )
        else:
            text = (
                f"\U0001F4DA {title}.\n"
                f"\U0001F4C5 {date_fmt}{time_str}\n\n"
                "See you! \U0001F4AA"
            )
        try:
            await bot.send_message(student["telegram_id"], text)
            log.info(f"Напоминание ({day_diff}д): {student['name']}")
        except Exception as e:
            log.warning(f"Ошибка: {e}")

async def send_payment_reminders():
    log.info("Напоминания об оплате...")
    for s in db.get_students_with_debt():
        if not s.get("telegram_id"): continue
        lang = s.get("telegram_lang","ru")
        fmt = f"{s['debt']:,}".replace(",", " ")
        try:
            await bot.send_message(s["telegram_id"], t(lang, "reminder_payment", amount=fmt))
        except Exception as e:
            log.warning(f"Ошибка: {e}")


# ── Любое сообщение — показываем меню ────────────────────────────────────────

@dp.message(F.text)
async def handle_any_message(msg: Message, state: FSMContext):
    # Пропускаем преподавателя
    if msg.from_user.id == TUTOR_ID: return

    # Проверяем нет ли активного FSM состояния
    current = await state.get_state()
    if current is not None: return

    lang = get_lang(msg.from_user)
    student = db.get_student_by_telegram(msg.from_user.id)
    pending = db.get_pending_application(msg.from_user.id)

    if student:
        await msg.answer(
            "Выберите действие 👇" if lang=="ru" else "Choose an action 👇",
            reply_markup=main_menu_kb(lang)
        )
    elif pending:
        await msg.answer(
            "⏳ Ваша заявка на рассмотрении." if lang=="ru" else "⏳ Your application is pending.",
            reply_markup=main_menu_kb(lang, has_pending=True)
        )
    else:
        await msg.answer(
            t(lang, "start") + ("\n\n💡 Если вы уже записаны — напишите /link Имя" if lang=="ru"
                                else "\n\n💡 If enrolled — write /link YourName"),
            reply_markup=main_menu_kb(lang)
        )

# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(send_lesson_reminders, "cron", hour=10, minute=0)
    scheduler.add_job(send_payment_reminders, "cron", day_of_week="mon", hour=10, minute=0)
    scheduler.start()
    log.info("Бот запущен!")
    try:
        await bot.send_message(
            TUTOR_ID,
            "🤖 Бот запущен!\n\n"
            "Команды:\n"
            "/schedule_set — утвердить расписание ученика\n"
            "/students — все ученики\n"
            "/debtors — должники\n"
            "/testremind — тест напоминаний"
        )
    except Exception:
        pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
