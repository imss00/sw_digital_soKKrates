const TOKEN_KEY = "paperback_auth_token";
const MOCK_KEY = "paperback_mock_logged_in";
const USER_KEY = "paperback_auth_user";
const API_BASE = "https://paperback-agent.fly.dev";

function hasStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function read(key) {
  if (!hasStorage()) return null;
  return window.localStorage.getItem(key);
}

function write(key, value) {
  if (!hasStorage()) return;
  window.localStorage.setItem(key, value);
}

function remove(key) {
  if (!hasStorage()) return;
  window.localStorage.removeItem(key);
}

function parseJwtPayload(token) {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export function initAuthFromUrl() {
  if (!hasStorage()) return;

  const url = new URL(window.location.href);
  const token = url.searchParams.get("token");
  const userId = url.searchParams.get("user_id");

  if (token) {
    write(TOKEN_KEY, token);
    remove(MOCK_KEY);
    if (userId) {
      write(USER_KEY, JSON.stringify({ id: Number(userId) || null }));
    } else {
      const payload = parseJwtPayload(token);
      if (payload?.sub) {
        write(USER_KEY, JSON.stringify({ id: Number(payload.sub) || null }));
      }
    }
    url.searchParams.delete("token");
    url.searchParams.delete("user_id");
    window.history.replaceState({}, "", url.toString());
  }
}

export function isLoggedIn() {
  if (!hasStorage()) return false;
  return Boolean(read(TOKEN_KEY) || read(MOCK_KEY) === "true");
}

export function mockLogin() {
  write(MOCK_KEY, "true");
  remove(TOKEN_KEY);
  write(USER_KEY, JSON.stringify({ id: 3, name: "Mock User" }));
}

export async function startGoogleOAuthLogin() {
  const res = await fetch(`${API_BASE}/auth/google`);
  if (!res.ok) {
    throw new Error(`oauth start failed: HTTP ${res.status}`);
  }
  const data = await res.json();
  if (!data.auth_url) {
    throw new Error("oauth start failed: missing auth_url");
  }
  window.location.assign(data.auth_url);
}

export function logout() {
  remove(MOCK_KEY);
  remove(TOKEN_KEY);
  remove(USER_KEY);
}

export function getAuthUser() {
  const raw = read(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function getAuthHeaderIfReal() {
  const token = read(TOKEN_KEY);
  if (!token) return null;
  return { Authorization: `Bearer ${token}` };
}
