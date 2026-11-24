// Orion Companion: talks ONLY to your local Orion at http://127.0.0.1:<port>, using a secret token you paste once.
// It shares your tab list (titles + URLs) with Orion, and sends a page's text only when Orion asks for a tab
// that you picked in Orion's + menu.
const DEFAULTS = { port: 8765, token: "" };
let polling = false;

async function cfg() { return await chrome.storage.local.get(DEFAULTS); }

async function api(path, init = {}) {
  const { port, token } = await cfg();
  if (!token) throw new Error("no token set");
  return fetch(`http://127.0.0.1:${port}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Orion-Token": token },
  });
}

function browserName() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Edge";
  if (ua.includes("OPR/")) return "Opera";
  return "Chrome";
}

let pushTimer = null;
function schedulePush() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(pushTabs, 400);
}

async function pushTabs() {
  try {
    const tabs = await chrome.tabs.query({});
    const body = tabs
      .filter((t) => t.url && /^https?:|^file:/.test(t.url))
      .map((t) => ({ id: t.id, windowId: t.windowId, title: t.title || "", url: t.url, active: !!t.active }));
    await api("/tabs", { method: "POST", body: JSON.stringify({ browser: browserName(), tabs: body }) });
  } catch (e) { /* Orion not running yet: try again later */ }
}

async function handle(req) {
  let text = "", error = "";
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: req.tabId },
      func: () => (document.body ? document.body.innerText : "").slice(0, 80000),
    });
    text = (res && res[0] && res[0].result) || "";
  } catch (e) {
    error = "Couldn't read that tab: " + (e && e.message ? e.message : e);
  }
  try {
    await api("/result", { method: "POST", body: JSON.stringify({ id: req.id, text, error }) });
  } catch (e) {}
}

async function pollLoop() {
  if (polling) return;
  polling = true;
  try {
    for (;;) {
      try {
        const r = await api("/poll");
        if (!r.ok) { await new Promise((s) => setTimeout(s, 5000)); continue; }
        const { requests } = await r.json();
        for (const req of requests || []) handle(req);
      } catch (e) {
        await new Promise((s) => setTimeout(s, 5000));
      }
    }
  } finally {
    polling = false;
  }
}

function start() { pushTabs(); pollLoop(); }

chrome.tabs.onCreated.addListener(schedulePush);
chrome.tabs.onRemoved.addListener(schedulePush);
chrome.tabs.onUpdated.addListener((id, change) => { if (change.url || change.title || change.status) schedulePush(); });
chrome.tabs.onActivated.addListener(schedulePush);
chrome.runtime.onStartup.addListener(start);
chrome.runtime.onInstalled.addListener(start);
chrome.storage.onChanged.addListener(start);
chrome.alarms.create("orion-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => { pushTabs(); pollLoop(); });
start();
