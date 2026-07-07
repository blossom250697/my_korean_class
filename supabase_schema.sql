-- ════════════════════════════════════════════════════════════
-- СХЕМА БАЗЫ ДАННЫХ для Korean Tutor
-- Запустите этот SQL в Supabase → SQL Editor → New Query
-- ════════════════════════════════════════════════════════════

-- ── Ученики ──────────────────────────────────────────────────────────────────
CREATE TABLE students (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  level         TEXT,
  start_date    DATE,
  has_free      BOOLEAN DEFAULT FALSE,
  free_count    INTEGER DEFAULT 0,
  frequency     TEXT DEFAULT '2x',        -- '2x' | '3x'
  payment_type  TEXT DEFAULT 'monthly',   -- 'monthly' | 'perSession'
  notes         TEXT,
  telegram_id   BIGINT UNIQUE,            -- Telegram ID ученика (когда зарегистрируется)
  telegram_lang TEXT DEFAULT 'ru',        -- 'ru' | 'en'
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Заявки на запись (от бота) ────────────────────────────────────────────────
CREATE TABLE applications (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_id   BIGINT NOT NULL,
  name          TEXT NOT NULL,
  level         TEXT,
  frequency     TEXT,
  preferred_time TEXT,
  message       TEXT,
  lang          TEXT DEFAULT 'ru',
  status        TEXT DEFAULT 'new',       -- 'new' | 'approved' | 'rejected'
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Занятия ───────────────────────────────────────────────────────────────────
CREATE TABLE sessions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id    UUID REFERENCES students(id) ON DELETE CASCADE,
  date          DATE NOT NULL,
  held          BOOLEAN DEFAULT FALSE,
  paid          BOOLEAN DEFAULT FALSE,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(student_id, date)
);

-- ── Помесячные оплаты ─────────────────────────────────────────────────────────
CREATE TABLE monthly_payments (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id    UUID REFERENCES students(id) ON DELETE CASCADE,
  year          INTEGER NOT NULL,
  month         INTEGER NOT NULL,
  paid          BOOLEAN DEFAULT FALSE,
  paid_at       TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(student_id, year, month)
);

-- ── Напоминания (лог отправленных) ───────────────────────────────────────────
CREATE TABLE reminders_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id    UUID REFERENCES students(id) ON DELETE CASCADE,
  session_id    UUID REFERENCES sessions(id) ON DELETE CASCADE,
  type          TEXT,                     -- 'lesson' | 'payment'
  sent_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ── Включаем Row Level Security ───────────────────────────────────────────────
ALTER TABLE students         ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications     ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders_log    ENABLE ROW LEVEL SECURITY;

-- Разрешаем всё для service_role (бот использует service key)
CREATE POLICY "service_all" ON students         FOR ALL USING (true);
CREATE POLICY "service_all" ON applications     FOR ALL USING (true);
CREATE POLICY "service_all" ON sessions         FOR ALL USING (true);
CREATE POLICY "service_all" ON monthly_payments FOR ALL USING (true);
CREATE POLICY "service_all" ON reminders_log    FOR ALL USING (true);
