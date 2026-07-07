from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import date, timedelta

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Ученики ───────────────────────────────────────────────────────────────────

def get_student_by_telegram(telegram_id: int):
    r = sb.table("students").select("*").eq("telegram_id", telegram_id).execute()
    return r.data[0] if r.data else None

def get_all_students():
    return sb.table("students").select("*").execute().data

def create_student(data: dict):
    return sb.table("students").insert(data).execute().data[0]

def update_student(student_id: str, data: dict):
    sb.table("students").update(data).eq("id", student_id).execute()

# ── Заявки ────────────────────────────────────────────────────────────────────

def create_application(data: dict):
    return sb.table("applications").insert(data).execute().data[0]

def get_new_applications():
    return sb.table("applications").select("*").eq("status", "new").order("created_at").execute().data

def update_application(app_id: str, status: str):
    sb.table("applications").update({"status": status}).eq("id", app_id).execute()

# ── Занятия ───────────────────────────────────────────────────────────────────

def get_sessions_for_student(student_id: str):
    return sb.table("sessions").select("*").eq("student_id", student_id).order("date").execute().data

def add_session(student_id: str, session_date: str):
    """Добавить занятие (игнорировать если уже есть)"""
    try:
        sb.table("sessions").insert({"student_id": student_id, "date": session_date}).execute()
    except Exception:
        pass  # уже существует

def get_tomorrow_sessions():
    """Занятия завтра — для напоминаний"""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return (
        sb.table("sessions")
        .select("*, students(*)")
        .eq("date", tomorrow)
        .eq("held", False)
        .execute()
        .data
    )

# ── Оплата ────────────────────────────────────────────────────────────────────

MONTHLY_RATES = {"2x": 300000, "3x": 450000}
SESSION_RATES = {"2x": 37500,  "3x": 37500}

def get_student_debt(student_id: str) -> int:
    """Считает долг ученика"""
    student = sb.table("students").select("*").eq("id", student_id).execute().data
    if not student:
        return 0
    student = student[0]

    sessions = get_sessions_for_student(student_id)
    payments = sb.table("monthly_payments").select("*").eq("student_id", student_id).execute().data

    free_count = student["free_count"] if student["has_free"] else 0
    held_sessions = sorted([s for s in sessions if s["held"]], key=lambda s: s["date"])

    debt = 0

    if student["payment_type"] == "monthly":
        # Месяца с проведёнными платными занятиями
        paid_months = {(p["year"], p["month"]) for p in payments if p["paid"]}
        months_with_lessons = set()
        for i, s in enumerate(held_sessions):
            if i >= free_count:
                d = s["date"][:7]  # YYYY-MM
                y, m = int(d[:4]), int(d[5:7])
                months_with_lessons.add((y, m))
        for ym in months_with_lessons:
            if ym not in paid_months:
                debt += MONTHLY_RATES[student["frequency"]]
    else:
        rate = SESSION_RATES[student["frequency"]]
        for i, s in enumerate(held_sessions):
            if i >= free_count and not s["paid"]:
                debt += rate

    return debt

def get_students_with_debt():
    """Все ученики у кого есть долг"""
    students = get_all_students()
    result = []
    for s in students:
        debt = get_student_debt(s["id"])
        if debt > 0:
            result.append({**s, "debt": debt})
    return result
