// API client for the FastAPI backend

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// NOTE: When running locally, set up a proxy in vite.config.js or use CORS on your FastAPI.
// For production, set VITE_API_BASE_URL to your deployed backend URL.

function getToken() {
  return localStorage.getItem("nipun_token");
}

function setToken(token) {
  localStorage.setItem("nipun_token", token);
}

function clearAuth() {
  localStorage.removeItem("nipun_token");
  localStorage.removeItem("nipun_user");
  localStorage.removeItem("nipun_profile");
  window.location.href = "/login";
}

// Guard every request with a timeout so a hung backend can't leave the UI spinner
// spinning forever — abort and surface a timeout Error into the normal error-card path.
const REQUEST_TIMEOUT_MS = 60000;

async function request(method, path, body, options = {}) {
  const headers = { ...options.headers };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.correlationId) headers["X-Correlation-ID"] = options.correlationId;

  const controller = new AbortController();
  const config = { method, headers, signal: controller.signal };

  if (body instanceof FormData) {
    config.body = body;
  } else if (body) {
    headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(body);
  }

  const timeoutMs = options.timeoutMs || REQUEST_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, config);
  } catch (err) {
    if (err?.name === "AbortError") {
      const timeoutErr = new Error("The request timed out. Please check your connection and try again.");
      timeoutErr.code = "TIMEOUT";
      throw timeoutErr;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  if (res.status === 401) {
    const data = await res.json().catch(() => ({}));
    const code = data?.error?.code || data?.detail?.code;
    if (code === "MISSING_TOKEN" || code === "INVALID_TOKEN") {
      clearAuth();
      return;
    }
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({ error: { message: "Request failed" } }));
    const err = new Error(data?.error?.message || data?.detail?.message || data?.detail || "Request failed");
    err.status = res.status;
    err.code = data?.error?.code || data?.detail?.code;
    err.correlationId = data?.error?.correlation_id || data?.detail?.correlation_id;
    throw err;
  }

  if (res.status === 204) return null;
  return res.json();
}

// Auth
export const auth = {
  signup: (data) => request("POST", "/auth/signup", data),
  login: (data) => request("POST", "/auth/login", data),
  resetPassword: (data) => request("POST", "/auth/reset-password", data),
};

// Profile
// The app uses camelCase profile keys (uiPreset, textScale, …) while the backend
// stores snake_case columns. These maps translate in both directions so callers can
// keep using camelCase everywhere. Keys that are identical in both cases (theme,
// motif, language, interests, ai_model, …) simply pass through unchanged.
const PROFILE_TO_SNAKE = {
  uiPreset: "ui_preset",
  textScale: "text_scale",
  highContrast: "high_contrast",
  voiceEnabled: "voice_enabled",
  festiveAccents: "festive_accents",
  ageBand: "age_band",
  gender: "gender",
  languagesKnown: "languages_known",
};
const PROFILE_TO_CAMEL = Object.fromEntries(
  Object.entries(PROFILE_TO_SNAKE).map(([camel, snake]) => [snake, camel])
);

function profileToSnake(data) {
  const out = {};
  for (const [k, v] of Object.entries(data || {})) {
    if (v === undefined) continue;
    out[PROFILE_TO_SNAKE[k] || k] = v;
  }
  return out;
}

function profileToCamel(data) {
  const out = {};
  for (const [k, v] of Object.entries(data || {})) {
    out[PROFILE_TO_CAMEL[k] || k] = v;
  }
  return out;
}

export const profile = {
  get: async () => profileToCamel(await request("GET", "/profile")),
  update: async (data) => profileToCamel(await request("PATCH", "/profile", profileToSnake(data))),
};

// Sessions
export const sessions = {
  list: (limit = 20, offset = 0) => request("GET", `/sessions?limit=${limit}&offset=${offset}`),
  create: (data) => request("POST", "/sessions", data),
  get: (id) => request("GET", `/sessions/${id}`),
  getMessages: (id, limit = 50) => request("GET", `/sessions/${id}/messages?limit=${limit}`),
  update: (id, data) => request("PATCH", `/sessions/${id}`, data),
  delete: (id) => request("DELETE", `/sessions/${id}`),
};

// Query
export const query = {
  send: (data, correlationId) => request("POST", "/query", data, { correlationId }),
};

// Feedback
export const feedback = {
  send: (data) => request("POST", "/feedback", data),
};

// Explain differently
export const explain = {
  differently: (data) => request("POST", "/explain-differently", data),
};

// Documents
export const documents = {
  upload: (formData) => request("POST", "/documents", formData),
  list: () => request("GET", "/documents"),
  get: (id) => request("GET", `/documents/${id}`),
  delete: (id) => request("DELETE", `/documents/${id}`),
  query: (id, data) => request("POST", `/documents/${id}/query`, data),
};

// Tools
export const tools = {
  list: () => request("GET", "/tools"),
  call: (data) => request("POST", "/tools/call", data),
  ingestBooks: (data) => request("POST", "/tools/ingest-books", data),
};

// Tasks
export const tasks = {
  list: () => request("GET", "/tasks"),
  preview: (data) => request("POST", "/tasks/preview", data),
  prepare: (data) => request("POST", "/tasks/prepare", data),
  confirm: (data) => request("POST", "/tasks/confirm", data),
  reject: (data) => request("POST", "/tasks/reject", data),
};

// Admin
export const admin = {
  init: () => request("POST", "/admin/init"),
  getUsers: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.role) qs.set("role", params.role);
    if (params.is_active !== undefined) qs.set("is_active", params.is_active);
    if (params.limit) qs.set("limit", params.limit);
    if (params.offset) qs.set("offset", params.offset);
    return request("GET", `/admin/users?${qs}`);
  },
  getUser: (id) => request("GET", `/admin/users/${id}`),
  updateUser: (id, data) => request("PATCH", `/admin/users/${id}`, data),
  deleteUser: (id) => request("DELETE", `/admin/users/${id}`),
  getUserSessions: (id) => request("GET", `/admin/users/${id}/sessions`),
  resetUserPassword: (id) => request("POST", `/admin/users/${id}/reset-password`),
  uploadDocument: (formData) => request("POST", "/admin/documents", formData),
};

// Generated files (deliverables: pptx/docx). The endpoint is auth-protected, so a plain
// <a href> won't carry the token — fetch with auth, then trigger a blob download.
export const files = {
  download: async (urlOrId, fallbackName) => {
    const path = urlOrId.startsWith("/") ? urlOrId : `/files/${urlOrId}`;
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${BASE_URL}${path}`, { headers });
    if (!res.ok) throw new Error("Download failed");
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const name = (m && m[1]) || fallbackName || "download";
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objUrl);
  },
};

// Health
export const health = {
  check: () => request("GET", "/health"),
};

// WebSocket
export function createWebSocket(sessionId) {
  const wsBase = BASE_URL.replace(/^http/, "ws");
  return new WebSocket(`${wsBase}/ws/${sessionId}`);
}

// IPA browser agent — plan a task, then run it live over its own WebSocket.
export const taskAgent = {
  start: (goal) => request("POST", "/task/start", { goal }),
};

export function createTaskWebSocket(taskId) {
  const wsBase = BASE_URL.replace(/^http/, "ws");
  return new WebSocket(`${wsBase}/ws/task/${taskId}`);
}

// Logs
export const logs = {
  send: (entries) => fetch(`${BASE_URL}/logs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entries),
  }).catch(() => {}),
};

export { getToken, setToken, clearAuth, BASE_URL };