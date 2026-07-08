from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import date, timedelta
import uuid

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Ученики ───────────────────────────────────────────────────────────────────

def get_student_by_telegram(telegram_id: int):
    r = sb.table("students").select("*").eq("telegram_id", telegram_id).execute()
    return r.data[0] if r.data else None

def get_all_students():
    return sb.table("students").select("*").execute().data

def create_student(data: dict):
    data["id"] = str(uuid.uuid4())
    return sb.table("students").insert(data).execute().data[0]

def update_student(student_id: str, data: dict):
    sb.table("students").update(data).eq("id", student_id).execute()

# ── Заявки ────────────────────────────────────────────────────────────────────

def create_application(data: dict):
    data["id"] = str(uuid.uuid4())
    return sb.table("applications").insert(data).execute().data[0]

def get_application(app_id: str):
    r = sb.table("applications").select("*").eq("id", app_id).execute()
    return r.data[0] if r.data else None

def update_application(app_id: str, status: str):
    sb.table("applications").update({"status": status}).eq("id", app_id).execute()

# ── Занятия ───────────────────────────────────────────────────────────────────

def get_sessions_for_student(student_id: str):
    return sb.table("sessions").select("*").eq("student_id", student_id).order("date").execute().data

def add_session(student_id: str, session_date: str):
    try:
        sb.table("sessions").insert({
            "id": str(uuid.uuid4()),
            "student_id": student_id,
            "date": session_date,
            "held": False,
            "paid": False
        }).execute()
    except Exception:
        pass

def add_session_direct(session: dict):
    """Добавить занятие с готовыми данными"""
    try:
        sb.table("sessions").insert(session).execute()
    except Exception as e:
        pass

def get_tomorrow_sessions():
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
    r = sb.table("students").select("*").eq("id", student_id).execute()
    if not r.data: return 0
    student = r.data[0]
    sessions = get_sessions_for_student(student_id)
    payments = sb.table("monthly_payments").select("*").eq("student_id", student_id).execute().data

    free_count = student["free_count"] if student["has_free"] else 0
    held = sorted([s for s in sessions if s["held"]], key=lambda s: s["date"])
    debt = 0

    if student["payment_type"] == "monthly":
        paid_months = {(p["year"], p["month"]) for p in payments if p["paid"]}
        months_with = set()
        for i, s in enumerate(held):
            if i >= free_count:
                y, m = int(s["date"][:4]), int(s["date"][5:7])
                months_with.add((y, m))
        for ym in months_with:
            if ym not in paid_months:
                debt += MONTHLY_RATES[student["frequency"]]
    else:
        rate = SESSION_RATES[student["frequency"]]
        for i, s in enumerate(held):
            if i >= free_count and not s["paid"]:
                debt += rate
    return debt

def get_students_with_debt():
    students = get_all_students()
    result = []
    for s in students:
        debt = get_student_debt(s["id"])
        if debt > 0:
            result.append({**s, "debt": debt})
    return result
