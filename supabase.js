// ─── Supabase клиент ──────────────────────────────────────────────────────────
// Конфиг берётся из localStorage (вводится при первом запуске)

const CONFIG_KEY = 'kt_supabase_config';

export function getConfig() {
  try { return JSON.parse(localStorage.getItem(CONFIG_KEY) || 'null'); }
  catch { return null; }
}

export function saveConfig(url, key) {
  localStorage.setItem(CONFIG_KEY, JSON.stringify({ url, key }));
}

export function clearConfig() {
  localStorage.removeItem(CONFIG_KEY);
}

// Создаём минимальный Supabase клиент без npm пакета
function createClient(url, key) {
  const headers = {
    'apikey': key,
    'Authorization': `Bearer ${key}`,
    'Content-Type': 'application/json',
    'Prefer': 'return=representation',
  };

  async function req(method, path, body) {
    const res = await fetch(`${url}/rest/v1/${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || `HTTP ${res.status}`);
    }
    return res.status === 204 ? [] : res.json();
  }

  return {
    from: (table) => ({
      select: (cols = '*') => ({
        eq: (col, val) => req('GET', `${table}?select=${cols}&${col}=eq.${encodeURIComponent(val)}&order=created_at`),
        order: (col) => req('GET', `${table}?select=${cols}&order=${col}`),
        execute: () => req('GET', `${table}?select=${cols}&order=created_at`),
      }),
      insert: (data) => req('POST', table, data),
      update: (data, col, val) => req('PATCH', `${table}?${col}=eq.${encodeURIComponent(val)}`, data),
      upsert: (data) => req('POST', table, data, { headers: { ...headers, 'Prefer': 'resolution=merge-duplicates,return=representation' } }),
      delete: (col, val) => req('DELETE', `${table}?${col}=eq.${encodeURIComponent(val)}`),
    }),
    rpc: (fn, params) => req('POST', `rpc/${fn}`, params),
  };
}

// Синглтон клиента
let _sb = null;

export function getClient() {
  if (_sb) return _sb;
  const cfg = getConfig();
  if (!cfg) throw new Error('Supabase не настроен');
  _sb = createClient(cfg.url, cfg.key);
  return _sb;
}

export function resetClient() { _sb = null; }

// ─── API функции ──────────────────────────────────────────────────────────────

export const api = {
  // Ученики
  async getStudents() {
    const sb = getClient();
    return sb.from('students').select('*').execute();
  },
  async addStudent(data) {
    const sb = getClient();
    return sb.from('students').insert({ ...data, id: crypto.randomUUID() });
  },
  async updateStudent(id, data) {
    const sb = getClient();
    return sb.from('students').update(data, 'id', id);
  },
  async deleteStudent(id) {
    const sb = getClient();
    await sb.from('sessions').delete('student_id', id);
    await sb.from('monthly_payments').delete('student_id', id);
    return sb.from('students').delete('id', id);
  },

  // Занятия
  async getSessions() {
    const sb = getClient();
    return sb.from('sessions').select('*').execute();
  },
  async addSession(studentId, date) {
    const sb = getClient();
    try {
      return await sb.from('sessions').insert({ id: crypto.randomUUID(), student_id: studentId, date, held: false, paid: false });
    } catch { return []; }
  },
  async deleteSession(id) {
    const sb = getClient();
    return sb.from('sessions').delete('id', id);
  },
  async toggleSession(id, field, value) {
    const sb = getClient();
    return sb.from('sessions').update({ [field]: value }, 'id', id);
  },

  // Помесячные оплаты
  async getPayments() {
    const sb = getClient();
    return sb.from('monthly_payments').select('*').execute();
  },
  async setMonthPayment(studentId, year, month, paid) {
    const sb = getClient();
    // Проверяем существует ли запись
    const existing = await sb.from('monthly_payments').select('*').eq('student_id', studentId);
    const found = existing.find(p => p.year === year && p.month === month);
    if (found) {
      return sb.from('monthly_payments').update({ paid }, 'id', found.id);
    } else {
      return sb.from('monthly_payments').insert({ id: crypto.randomUUID(), student_id: studentId, year, month, paid });
    }
  },
};
