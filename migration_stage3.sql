-- ═══════════════════════════════════════════════════════════════════════════
-- Миграция Stage 3: статусы занятий + защита от двойного бронирования
-- Запустите в Supabase → SQL Editor
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. Добавляем колонки в sessions
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'scheduled';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS rescheduled_from UUID;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS reschedule_reason TEXT;

-- Обновляем существующие записи
UPDATE sessions SET status = 'completed' WHERE held = true;
UPDATE sessions SET status = 'scheduled' WHERE held = false AND status IS NULL;

-- 2. Уникальный индекс: один ученик — одно занятие в одно время
CREATE UNIQUE INDEX IF NOT EXISTS sessions_student_date_time_unique
  ON sessions(student_id, date, time)
  WHERE status = 'scheduled';

-- 3. Добавляем confirmed_session_id в applications
ALTER TABLE applications ADD COLUMN IF NOT EXISTS confirmed_session_id UUID;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS session_date TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS session_time TEXT;

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. RPC: confirm_lesson — атомарное подтверждение (защита от двойного нажатия)
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION confirm_lesson(
    p_app_id     UUID,
    p_student_id UUID,
    p_date       TEXT,
    p_time       TEXT,
    p_session_id UUID
) RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE
    v_app       applications%ROWTYPE;
    v_conflict  INTEGER;
BEGIN
    -- Блокируем заявку чтобы избежать гонки
    SELECT * INTO v_app FROM applications WHERE id = p_app_id FOR UPDATE;

    IF NOT FOUND THEN
        RETURN json_build_object('ok', false, 'reason', 'app_not_found');
    END IF;

    -- Уже подтверждена?
    IF v_app.status IN ('approved', 'rejected', 'cancelled') THEN
        RETURN json_build_object('ok', false, 'reason', 'already_processed',
                                 'status', v_app.status,
                                 'session_id', v_app.confirmed_session_id);
    END IF;

    -- Проверяем конфликт по времени (другой ученик уже занял слот)
    SELECT COUNT(*) INTO v_conflict
    FROM sessions
    WHERE date = p_date
      AND time = p_time
      AND status = 'scheduled'
      AND id != p_session_id;

    IF v_conflict > 0 THEN
        RETURN json_build_object('ok', false, 'reason', 'time_conflict');
    END IF;

    -- Создаём занятие
    INSERT INTO sessions (id, student_id, date, time, held, paid, status)
    VALUES (p_session_id, p_student_id, p_date, p_time, false, false, 'scheduled')
    ON CONFLICT (id) DO NOTHING;

    -- Обновляем заявку
    UPDATE applications
    SET status = 'approved',
        confirmed_session_id = p_session_id,
        session_date = p_date,
        session_time = p_time
    WHERE id = p_app_id;

    RETURN json_build_object('ok', true, 'session_id', p_session_id);

EXCEPTION WHEN unique_violation THEN
    RETURN json_build_object('ok', false, 'reason', 'time_conflict');
END;
$$;

-- ═══════════════════════════════════════════════════════════════════════════
-- 5. RPC: reschedule_lesson — атомарный перенос
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION reschedule_lesson(
    p_old_session_id UUID,
    p_new_session_id UUID,
    p_student_id     UUID,
    p_new_date       TEXT,
    p_new_time       TEXT,
    p_reason         TEXT DEFAULT ''
) RETURNS JSON LANGUAGE plpgsql AS $$
DECLARE
    v_conflict INTEGER;
BEGIN
    -- Проверяем конфликт в новом времени
    SELECT COUNT(*) INTO v_conflict
    FROM sessions
    WHERE date = p_new_date
      AND time = p_new_time
      AND status = 'scheduled'
      AND id != p_new_session_id;

    IF v_conflict > 0 THEN
        RETURN json_build_object('ok', false, 'reason', 'time_conflict');
    END IF;

    -- Отменяем старое занятие
    UPDATE sessions
    SET status = 'rescheduled', cancelled_at = NOW()
    WHERE id = p_old_session_id AND student_id = p_student_id;

    IF NOT FOUND THEN
        RETURN json_build_object('ok', false, 'reason', 'old_session_not_found');
    END IF;

    -- Создаём новое
    INSERT INTO sessions (id, student_id, date, time, held, paid, status, rescheduled_from, reschedule_reason)
    VALUES (p_new_session_id, p_student_id, p_new_date, p_new_time, false, false, 'scheduled', p_old_session_id, p_reason)
    ON CONFLICT (id) DO NOTHING;

    RETURN json_build_object('ok', true, 'new_session_id', p_new_session_id);

EXCEPTION WHEN unique_violation THEN
    RETURN json_build_object('ok', false, 'reason', 'time_conflict');
END;
$$;

-- ═══════════════════════════════════════════════════════════════════════════
-- 6. RPC: cancel_lesson
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION cancel_lesson(
    p_session_id UUID,
    p_reason     TEXT DEFAULT ''
) RETURNS JSON LANGUAGE plpgsql AS $$
BEGIN
    UPDATE sessions
    SET status = 'cancelled', cancelled_at = NOW(), reschedule_reason = p_reason
    WHERE id = p_session_id AND status = 'scheduled';

    IF NOT FOUND THEN
        RETURN json_build_object('ok', false, 'reason', 'not_found_or_not_scheduled');
    END IF;

    RETURN json_build_object('ok', true);
END;
$$;

-- ═══════════════════════════════════════════════════════════════════════════
-- Готово! Проверьте что функции созданы:
-- SELECT routine_name FROM information_schema.routines
-- WHERE routine_type = 'FUNCTION' AND routine_name IN ('confirm_lesson','reschedule_lesson','cancel_lesson');
-- ═══════════════════════════════════════════════════════════════════════════
