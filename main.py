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
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, TUTOR_ID, TEXTS
import db

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
    message   = State()  # доп. сообщение

# ── FSM: подтверждение расписания преподавателем ──────────────────────────────

class ConfirmSchedule(StatesGroup):
    select_app  = State()  # выбор заявки (если несколько)
    frequency   = State()  # частота занятий
    days        = State()  # дни недели
    time_slot   = State()  # время начала занятия
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

    greeting = f"Добро пожаловать, {student['name']}! 👋\n\n" if student else ""
    await msg.answer(greeting + t(lang, "start"))

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
    await msg.answer(t(lang, "ask_message"))
    await state.set_state(ApplyForm.message)

@dp.message(ApplyForm.message)
async def apply_done(msg: Message, state: FSMContext):
    data = await state.get_data(); lang = data["lang"]
    app = db.create_application({
        "telegram_id":    msg.from_user.id,
        "name":           data["name"],
        "level":          data.get("level"),
        "frequency":      data.get("frequency"),
        "preferred_time": data.get("wishes"),
        "message":        msg.text if msg.text.lower() not in ("нет","no","-") else None,
        "lang":           lang,
        "status":         "new",
    })
    await msg.answer(t(lang, "applied"))

    freq_label = {"2x":"2 раза/нед","3x":"3 раза/нед"}.get(data.get("frequency",""),"")
    notif = (
        f"📬 <b>Новая заявка!</b>\n\n"
        f"👤 {data['name']}\n"
        f"📊 Уровень: {data.get('level','—')}\n"
        f"📅 Желаемая частота: {freq_label}\n"
        f"⏰ Пожелания по времени: {data.get('wishes','—')}\n"
        f"💬 {msg.text}\n"
        f"🌐 {'🇷🇺' if lang=='ru' else '🇺🇸'}\n"
        f"🆔 <code>{msg.from_user.id}</code>\n\n"
        f"Когда договоритесь о расписании — используй /schedule_set для добавления в систему."
    )
    await bot.send_message(TUTOR_ID, notif, parse_mode="HTML")
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
    if not data.get("selected_days"):
        await cb.answer("Выбери хотя бы один день!", show_alert=True); return
    await cb.message.edit_text(
        "⏰ <b>Укажи время начала занятия</b>\n\nНапример: <code>11:00</code>",
        parse_mode="HTML"
    )
    await state.set_state(ConfirmSchedule.time_slot)
    await cb.answer()

@dp.message(ConfirmSchedule.time_slot)
async def confirm_time(msg: Message, state: FSMContext):
    await state.update_data(time_slot=msg.text.strip())
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
    lines = ["📅 <b>Ближайшие занятия:</b>\n" if lang=="ru" else "📅 <b>Upcoming lessons:</b>\n"]
    for s in upcoming[:5]:
        lines.append(f"• {datetime.fromisoformat(s['date']).strftime('%d.%m.%Y')}")
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
            "/schedule_set — утвердить расписание после договорённости с учеником\n"
            "/students — список всех учеников\n"
            "/debtors — должники\n"
            "/testremind — тест напоминаний о занятиях\n"
            "/testpayment — тест напоминаний об оплате",
            parse_mode="HTML"
        )
    else:
        lang = get_lang(msg.from_user)
        await msg.answer(t(lang, "start"))

# ── Напоминания ───────────────────────────────────────────────────────────────

async def send_lesson_reminders():
    log.info("Напоминания о занятиях...")
    for s in db.get_tomorrow_sessions():
        student = s.get("students")
        if not student or not student.get("telegram_id"): continue
        lang = student.get("telegram_lang","ru")
        date_fmt = datetime.fromisoformat(s["date"]).strftime("%d.%m.%Y")
        try:
            await bot.send_message(student["telegram_id"], t(lang, "reminder_lesson", date=date_fmt))
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
