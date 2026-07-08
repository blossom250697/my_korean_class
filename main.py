"""
Korean Tutor Bot
Запуск: python main.py
"""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config import BOT_TOKEN, TUTOR_ID, TEXTS
import db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── FSM: анкета заявки ────────────────────────────────────────────────────────

class ApplyForm(StatesGroup):
    lang      = State()
    name      = State()
    level     = State()
    frequency = State()
    time      = State()
    message   = State()

# ── Определяем язык пользователя ─────────────────────────────────────────────

def get_lang(user) -> str:
    """ru по умолчанию, en если язык не русский"""
    lc = user.language_code or "ru"
    return "en" if not lc.startswith("ru") else "ru"

def t(lang: str, key: str, **kwargs) -> str:
    text = TEXTS[lang].get(key, TEXTS["ru"].get(key, key))
    return text.format(**kwargs) if kwargs else text

# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    lang = get_lang(msg.from_user)

    # Проверяем — уже ученик?
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        await msg.answer(
            f"{'Добро пожаловать' if lang=='ru' else 'Welcome'}, {student['name']}! 👋\n\n"
            + t(lang, "start")
        )
    else:
        await msg.answer(t(lang, "start"))

# ── /apply — подать заявку ───────────────────────────────────────────────────

@dp.message(Command("apply"))
async def cmd_apply(msg: Message, state: FSMContext):
    # Уже есть заявка или ученик?
    student = db.get_student_by_telegram(msg.from_user.id)
    if student:
        lang = student.get("telegram_lang", "ru")
        await msg.answer(
            "Вы уже наш ученик! 🎓" if lang=="ru" else "You are already our student! 🎓"
        )
        return

    lang = get_lang(msg.from_user)
    await state.update_data(lang=lang)

    # Выбор языка общения
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
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(name=msg.text)
    await msg.answer(t(lang, "ask_level"))
    await state.set_state(ApplyForm.level)

@dp.message(ApplyForm.level)
async def apply_level(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(level=msg.text)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang,"freq_2x"), callback_data="freq_2x"),
        InlineKeyboardButton(text=t(lang,"freq_3x"), callback_data="freq_3x"),
    ]])
    await msg.answer(t(lang, "ask_frequency"), reply_markup=kb)
    await state.set_state(ApplyForm.frequency)

@dp.callback_query(ApplyForm.frequency, F.data.startswith("freq_"))
async def apply_freq(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    freq = cb.data.split("_")[1]  # "2x" | "3x"
    await state.update_data(frequency=freq)
    await cb.message.edit_text(t(lang, "ask_time"))
    await state.set_state(ApplyForm.time)
    await cb.answer()

@dp.message(ApplyForm.time)
async def apply_time(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    await state.update_data(preferred_time=msg.text)
    await msg.answer(t(lang, "ask_message"))
    await state.set_state(ApplyForm.message)

@dp.message(ApplyForm.message)
async def apply_done(msg: Message, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]

    # Сохраняем заявку в базу
    app = db.create_application({
        "telegram_id":    msg.from_user.id,
        "name":           data["name"],
        "level":          data.get("level"),
        "frequency":      data.get("frequency"),
        "preferred_time": data.get("preferred_time"),
        "message":        msg.text if msg.text.lower() not in ("нет","no","-") else None,
        "lang":           lang,
    })

    # Отправляем ученику подтверждение
    await msg.answer(t(lang, "applied"))

    # Уведомляем преподавателя
    freq_label = {"2x": "2 раза/нед", "3x": "3 раза/нед"}.get(data.get("frequency",""),"")
    notif = (
        f"📬 <b>Новая заявка!</b>\n\n"
        f"👤 Имя: {data['name']}\n"
        f"📊 Уровень: {data.get('level','—')}\n"
        f"📅 Частота: {freq_label}\n"
        f"⏰ Удобное время: {data.get('preferred_time','—')}\n"
        f"💬 Сообщение: {msg.text}\n"
        f"🌐 Язык: {'🇷🇺' if lang=='ru' else '🇺🇸'}\n"
        f"🆔 Telegram ID: <code>{msg.from_user.id}</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять",   callback_data=f"approve_{app['id']}_{msg.from_user.id}_{lang}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app['id']}_{msg.from_user.id}_{lang}"),
    ]])

    await bot.send_message(TUTOR_ID, notif, parse_mode="HTML", reply_markup=kb)
    await state.clear()

# ── Преподаватель: принять/отклонить заявку ───────────────────────────────────

@dp.callback_query(F.data.startswith("approve_"))
async def approve_application(cb: CallbackQuery):
    _, app_id, student_tg_id, lang = cb.data.split("_", 3)
    db.update_application(app_id, "approved")

    # Обновляем сообщение у преподавателя
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"✅ Заявка принята. Уведомление отправлено ученику.")

    # Уведомляем ученика
    await bot.send_message(int(student_tg_id), t(lang, "approved"))
    await cb.answer()

@dp.callback_query(F.data.startswith("reject_"))
async def reject_application(cb: CallbackQuery):
    _, app_id, student_tg_id, lang = cb.data.split("_", 3)
    db.update_application(app_id, "rejected")

    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"❌ Заявка отклонена. Уведомление отправлено ученику.")

    await bot.send_message(int(student_tg_id), t(lang, "rejected"))
    await cb.answer()

# ── /schedule — расписание ученика ────────────────────────────────────────────

@dp.message(Command("schedule"))
async def cmd_schedule(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы. Подайте заявку: /apply")
        return

    lang = student.get("telegram_lang", "ru")
    sessions = db.get_sessions_for_student(student["id"])
    upcoming = [s for s in sessions if s["date"] >= datetime.now().date().isoformat() and not s["held"]]

    if not upcoming:
        await msg.answer("📅 Ближайших занятий нет." if lang=="ru" else "📅 No upcoming lessons.")
        return

    lines = ["📅 <b>Ближайшие занятия:</b>\n" if lang=="ru" else "📅 <b>Upcoming lessons:</b>\n"]
    for s in upcoming[:5]:
        d = datetime.fromisoformat(s["date"]).strftime("%d.%m.%Y")
        lines.append(f"• {d}")

    await msg.answer("\n".join(lines), parse_mode="HTML")

# ── /payment — статус оплаты ──────────────────────────────────────────────────

@dp.message(Command("payment"))
async def cmd_payment(msg: Message):
    student = db.get_student_by_telegram(msg.from_user.id)
    if not student:
        await msg.answer("Вы ещё не зарегистрированы. Подайте заявку: /apply")
        return

    lang = student.get("telegram_lang", "ru")
    debt = db.get_student_debt(student["id"])

    if debt == 0:
        text = "✅ Оплата в порядке, долгов нет!" if lang=="ru" else "✅ All paid, no debts!"
    else:
        fmt = f"{debt:,}".replace(",", " ")
        text = (
            f"💳 Задолженность: <b>{fmt} ₩</b>\n\nПожалуйста, оплатите при возможности."
            if lang=="ru" else
            f"💳 Outstanding balance: <b>{fmt} ₩</b>\n\nPlease pay when you can."
        )

    await msg.answer(text, parse_mode="HTML")

# ── Команды только для преподавателя ─────────────────────────────────────────

def tutor_only(func):
    async def wrapper(msg: Message, *args, **kwargs):
        if msg.from_user.id != TUTOR_ID:
            await msg.answer("⛔ Нет доступа")
            return
        return await func(msg, *args, **kwargs)
    return wrapper

@dp.message(Command("debtors"))
@tutor_only
async def cmd_debtors(msg: Message):
    debtors = db.get_students_with_debt()
    if not debtors:
        await msg.answer("🎉 Долгов нет!")
        return

    lines = ["💸 <b>Должники:</b>\n"]
    total = 0
    for s in debtors:
        fmt = f"{s['debt']:,}".replace(",", " ")
        lines.append(f"• {s['name']} — {fmt} ₩")
        total += s["debt"]

    fmt_total = f"{total:,}".replace(",", " ")
    lines.append(f"\n<b>Итого: {fmt_total} ₩</b>")
    await msg.answer("\n".join(lines), parse_mode="HTML")

@dp.message(Command("students"))
@tutor_only
async def cmd_students(msg: Message):
    students = db.get_all_students()
    if not students:
        await msg.answer("Учеников нет.")
        return

    freq = {"2x": "2×/нед", "3x": "3×/нед"}
    lines = [f"👥 <b>Ученики ({len(students)}):</b>\n"]
    for s in students:
        tg = f" (@{s['telegram_id']})" if s.get("telegram_id") else " (не в боте)"
        lines.append(f"• {s['name']} — {freq.get(s['frequency'],'')} {tg}")

    await msg.answer("\n".join(lines), parse_mode="HTML")

# ── Планировщик напоминаний ───────────────────────────────────────────────────

async def send_lesson_reminders():
    """Каждый день в 10:00 — напоминания о завтрашних занятиях"""
    log.info("Отправка напоминаний о занятиях...")
    sessions = db.get_tomorrow_sessions()

    for s in sessions:
        student = s.get("students")
        if not student or not student.get("telegram_id"):
            continue

        lang = student.get("telegram_lang", "ru")
        date_fmt = datetime.fromisoformat(s["date"]).strftime("%d.%m.%Y")

        try:
            await bot.send_message(
                student["telegram_id"],
                t(lang, "reminder_lesson", date=date_fmt)
            )
            log.info(f"Напоминание отправлено: {student['name']}")
        except Exception as e:
            log.warning(f"Не удалось отправить напоминание {student['name']}: {e}")

async def send_payment_reminders():
    """Каждый понедельник в 10:00 — напоминания о долгах"""
    log.info("Отправка напоминаний об оплате...")
    debtors = db.get_students_with_debt()

    for s in debtors:
        if not s.get("telegram_id"):
            continue

        lang = s.get("telegram_lang", "ru")
        fmt  = f"{s['debt']:,}".replace(",", " ")

        try:
            await bot.send_message(
                s["telegram_id"],
                t(lang, "reminder_payment", amount=fmt)
            )
            log.info(f"Напоминание об оплате: {s['name']}")
        except Exception as e:
            log.warning(f"Не удалось: {s['name']}: {e}")

# ── Запуск ────────────────────────────────────────────────────────────────────

async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # Напоминания о занятиях — каждый день в 10:00 (по Сеулу)
    scheduler.add_job(send_lesson_reminders, "cron", hour=10, minute=0)

    # Напоминания об оплате — каждый понедельник в 10:00
    scheduler.add_job(send_payment_reminders, "cron", day_of_week="mon", hour=10, minute=0)

    scheduler.start()
    log.info("Бот запущен!")

    # Сообщение преподавателю при старте
    try:
        await bot.send_message(TUTOR_ID, "🤖 Бот запущен и готов к работе!")
    except Exception:
        pass

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
