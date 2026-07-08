-- Добавить колонку для хранения выбранных дней недели в заявке
-- Запустите в Supabase → SQL Editor
ALTER TABLE applications ADD COLUMN IF NOT EXISTS preferred_days INTEGER[] DEFAULT '{}';
