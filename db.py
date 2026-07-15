from config import SUPABASE_URL, SUPABASE_KEY
from datetime import date, timedelta
import uuid
import httpx

# ── Минимальный Supabase клиент без gotrue ────────────────────────────────────
# Используем чистый httpx вместо supabase-py чтобы избежать конфликтов версий

class SupabaseClient:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip('/')
        self.headers = {
            'apikey': key,
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation',
        }

    def _get(self, table: str, params: dict = None) -> list:
        with httpx.Client() as client:
            r = client.get(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                params=params or {}
            )
            r.raise_for_status()
            return r.json()

    def _post(self, table: str, data: dict, prefer: str = 'return=representation') -> dict:
        headers = {**self.headers, 'Prefer': prefer}
        with httpx.Client() as client:
            r = client.post(
                f"{self.url}/rest/v1/{table}",
                headers=headers,
                json=data
            )
            r.raise_for_status()
            result = r.json()
            return result[0] if isinstance(result, list) and result else result

    def _patch(self, table: str, data: dict, filters: dict) -> None:
        params = {k: f'eq.{v}' for k, v in filters.items()}
        with httpx.Client() as client:
            r = client.patch(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                params=params,
                json=data
            )
            r.raise_for_status()

    def _delete(self, table: str, filters: dict) -> None:
        params = {k: f'eq.{v}' for k, v in filters.items()}
        with httpx.Client() as client:
            r = client.delete(
                f"{self.url}/rest/v1/{table}",
                headers=self.headers,
                params=params
            )
            r.raise_for_status()

sb = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)

# ── Ученики ───────────────────────────────────────────────────────────────────

def get_student_by_telegram(telegram_id: int):
    r = sb._get('students', {'telegram_id': f'eq.{telegram_id}', 'select': '*'})
    return r[0] if r else None

def get_all_students():
    return sb._get('students', {'select': '*', 'order': 'created_at'})

def create_student(data: dict):
    data['id'] = str(uuid.uuid4())
    return sb._post('students', data)

def update_student(student_id: str, data: dict):
    sb._patch('students', data, {'id': student_id})

# ── Заявки ────────────────────────────────────────────────────────────────────

def create_application(data: dict):
    data['id'] = str(uuid.uuid4())
    return sb._post('applications', data)

def get_application(app_id: str):
    """Ищет заявку по UUID (с дефисами или без)"""
    import logging
    log = logging.getLogger(__name__)
    # Восстанавливаем дефисы если их нет (32 hex символа -> UUID формат)
    clean = app_id.replace("-", "")
    if len(clean) == 32:
        uuid_str = f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"
    else:
        uuid_str = app_id
    log.info(f"get_application: searching for id={uuid_str}")
    try:
        r = sb._get('applications', {'id': f'eq.{uuid_str}', 'select': '*'})
        log.info(f"get_application: result={r}")
        return r[0] if r else None
    except Exception as e:
        log.error(f"get_application error: {e}")
        return None

def get_new_applications():
    return sb._get('applications', {'status': 'eq.new', 'select': '*', 'order': 'created_at'})

def update_application(app_id: str, status: str):
    sb._patch('applications', {'status': status}, {'id': app_id})

def get_pending_application(telegram_id: int):
    """Активная заявка ученика (статус new)"""
    try:
        r = sb._get('applications', {
            'telegram_id': f'eq.{telegram_id}',
            'status': 'eq.new',
            'select': '*',
            'order': 'created_at.desc',
            'limit': '1',
        })
        return r[0] if r else None
    except Exception:
        return None

# ── Занятия ───────────────────────────────────────────────────────────────────

def get_sessions_for_student(student_id: str):
    return sb._get('sessions', {'student_id': f'eq.{student_id}', 'select': '*', 'order': 'date'})

def add_session_direct(session: dict):
    try:
        sb._post('sessions', session, prefer='return=minimal')
    except Exception as e:
        pass

def get_upcoming_sessions(days_ahead: int = 1) -> list:
    """Занятия сегодня и завтра (days_ahead=1) для напоминаний"""
    from datetime import date, timedelta
    today = date.today().isoformat()
    target = (date.today() + timedelta(days=days_ahead)).isoformat()
    # Берём занятия от сегодня до target включительно
    result = []
    for d in [today, target] if days_ahead >= 1 else [today]:
        rows = sb._get('sessions', {
            'date': f'eq.{d}',
            'held': 'eq.false',
            'select': '*,students(*)',
        })
        result.extend(rows)
    # Убираем дубликаты если days_ahead=0
    seen = set()
    unique = []
    for r in result:
        if r['id'] not in seen:
            seen.add(r['id'])
            unique.append(r)
    return unique

def get_tomorrow_sessions():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return sb._get('sessions', {
        'date': f'eq.{tomorrow}',
        'held': 'eq.false',
        'select': '*,students(*)',
    })

# ── Оплата ────────────────────────────────────────────────────────────────────

MONTHLY_RATES = {'2x': 300000, '3x': 450000}
SESSION_RATES = {'2x': 37500,  '3x': 37500}

def get_student_debt(student_id: str) -> int:
    students = sb._get('students', {'id': f'eq.{student_id}', 'select': '*'})
    if not students: return 0
    student = students[0]
    sessions = get_sessions_for_student(student_id)
    payments = sb._get('monthly_payments', {'student_id': f'eq.{student_id}', 'select': '*'})

    free_count = student['free_count'] if student['has_free'] else 0
    held = sorted([s for s in sessions if s['held']], key=lambda s: s['date'])
    debt = 0

    if student['payment_type'] == 'monthly':
        paid_months = {(p['year'], p['month']) for p in payments if p['paid']}
        months_with = set()
        for i, s in enumerate(held):
            if i >= free_count:
                y, m = int(s['date'][:4]), int(s['date'][5:7])
                months_with.add((y, m))
        for ym in months_with:
            if ym not in paid_months:
                debt += MONTHLY_RATES[student['frequency']]
    else:
        rate = SESSION_RATES[student['frequency']]
        for i, s in enumerate(held):
            if i >= free_count and not s['paid']:
                debt += rate
    return debt

def get_students_with_debt():
    students = get_all_students()
    result = []
    for s in students:
        debt = get_student_debt(s['id'])
        if debt > 0:
            result.append({**s, 'debt': debt})
    return result

# ── Постоянное расписание ученика ─────────────────────────────────────────────

def get_student_schedule(student_id: str) -> list:
    """Расписание ученика по дням недели"""
    try:
        return sb._get('student_schedule', {
            'student_id': f'eq.{student_id}',
            'select': '*',
            'order': 'dow'
        })
    except Exception:
        return []

def save_student_schedule(student_id: str, day_times: dict) -> None:
    """Сохраняет расписание: day_times = {'0': '11:00', '2': '15:00'}"""
    for dow_str, time in day_times.items():
        try:
            # Пробуем обновить существующую запись
            existing = sb._get('student_schedule', {
                'student_id': f'eq.{student_id}',
                'dow': f'eq.{dow_str}'
            })
            if existing:
                sb._patch('student_schedule', {'time': time}, {'id': existing[0]['id']})
            else:
                sb._post('student_schedule', {
                    'id': str(uuid.uuid4()),
                    'student_id': student_id,
                    'dow': int(dow_str),
                    'time': time,
                }, prefer='return=minimal')
        except Exception as e:
            pass
