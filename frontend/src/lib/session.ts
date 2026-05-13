// Anonymous session ID: stable per browser tab profile, stored in localStorage.
// Drives all v2 backend calls (assets, chat, drafts).

const KEY = "compismart_session_id";

function newId(): string {
  // RFC 4122 v4-ish, no external dep. crypto.randomUUID where available,
  // else a Math.random fallback.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return (crypto as Crypto).randomUUID();
  }
  return "sess-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

export function getSessionId(): string {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = newId();
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    // localStorage blocked (Safari private mode etc.) — fall back to per-tab.
    return newId();
  }
}

export function resetSession(): string {
  const id = newId();
  try {
    localStorage.setItem(KEY, id);
  } catch {}
  return id;
}
