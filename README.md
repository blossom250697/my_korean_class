# Korean Tutor Bot 🤖

Telegram бот для репетитора корейского языка.

---

## Быстрая настройка (30 минут)

### Шаг 1 — Supabase (база данных)

1. Идёшь на [supabase.com](https://supabase.com) → **Start for free**
2. Создаёшь новый проект (любое название, например `korean-tutor`)
3. Ждёшь ~2 минуты пока создаётся
4. Идёшь в **SQL Editor** → **New Query**
5. Копируешь весь текст из файла `supabase_schema.sql` → вставляешь → нажимаешь **Run**
6. Идёшь в **Settings → API**:
   - Копируешь **Project URL** → это `SUPABASE_URL`
   - Копируешь **anon public** key → это `SUPABASE_KEY`

### Шаг 2 — Узнать свой Telegram ID

1. Напиши своему боту `/start` в Telegram
2. Открой в браузере:
   ```
   https://api.telegram.org/bot<ТВОЙ_ТОКЕН>/getUpdates
   ```
3. Найди в ответе `"from":{"id":XXXXXXXXX}` — это твой ID

### Шаг 3 — Настроить переменные

Скопируй `.env.example` в `.env` и заполни:

```
BOT_TOKEN=8269694339:AAE1KpxJuXLkQLPpyJU-72Kspyz3rpbOCpo
TUTOR_CHAT_ID=твой_telegram_id
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_KEY=eyJhbGci...
```

### Шаг 4 — Деплой на Railway (бесплатно)

1. Идёшь на [railway.app](https://railway.app) → входишь через GitHub
2. **New Project → Deploy from GitHub repo** → выбираешь свой репозиторий
3. В настройках проекта → **Variables** → добавляешь все переменные из `.env`
4. Railway автоматически запустит бота через `Procfile`

### Шаг 5 — Загрузить на GitHub

```
korean-tutor-bot/
├── bot/
│   ├── main.py
│   ├── db.py
│   └── config.py
├── requirements.txt
├── Procfile
├── supabase_schema.sql
└── .env  ← НЕ загружать на GitHub! Добавь в .gitignore
```

Создай `.gitignore`:
```
.env
__pycache__/
*.pyc
```

---

## Что умеет бот

### Для учеников:
- `/start` — приветствие
- `/apply` — подать заявку (анкета на рус/англ)
- `/schedule` — ближайшие занятия
- `/payment` — статус оплаты

### Для тебя (преподавателя):
- Получаешь уведомление о каждой новой заявке
- Кнопки **Принять / Отклонить** прямо в сообщении
- `/debtors` — список должников с суммами
- `/students` — все ученики

### Автоматически:
- Каждый день в 10:00 — напоминания о завтрашних занятиях
- Каждый понедельник в 10:00 — напоминания об оплате должникам

---

## Как добавить ученика в систему

После принятия заявки — зайди в основную систему (korean-tutor.html)
и добавь ученика вручную. В следующей версии это будет автоматически.
