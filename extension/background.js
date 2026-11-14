// JARVIS browser extension: the background worker.
//
// It keeps one connection open to JARVIS on this computer (never to
// anything on the internet) and carries out the commands JARVIS sends:
// list tabs, open a page, read a page, click, type, and so on. Everything
// it does on a page is done by the functions in page.js.
//
// JARVIS decides what is allowed (approved sites, always-ask sites, never
// typing passwords). This worker only does as it is told by the paired
// JARVIS, and nothing is paired until you paste the pairing code.

importScripts("page.js");

// JARVIS listens on the first of these ports that is free on your computer
// (the same list is in jarvis/ui/server.py). Each is tried in turn.
const PORTS = [47821, 47822, 47823, 47824];
let socket = null;
let state = "not paired";  // shown in the popup
let trying = false;
let again = false;   // a new pairing code arrived while a try was under way
let lastPort = null; // the port that worked last time is tried first

async function pairingCode() {
  return (await chrome.storage.local.get("code")).code || "";
}

// Try one port. Resolves to "connected", "wrong pairing code" or "no answer".
function attempt(port, code) {
  return new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/browser?token=${encodeURIComponent(code)}`);
    let opened = false, settled = false;
    const settle = (outcome) => { if (!settled) { settled = true; resolve(outcome); } };
    ws.onopen = () => { opened = true; };
    ws.onerror = () => {};
    ws.onmessage = async (event) => {
      // The first message proves JARVIS accepted the pairing code.
      if (!settled) { socket = ws; state = "connected"; lastPort = port; settle("connected"); }
      const message = JSON.parse(event.data);
      if (message.type === "ping" || message.type === "hello") { if (message.type === "ping") ws.send(JSON.stringify({ type: "pong" })); return; }
      let reply;
      try {
        reply = { id: message.id, ok: true, result: await run(message.action, message.args || {}) };
      } catch (error) {
        reply = { id: message.id, ok: false, error: String((error && error.message) || error) };
      }
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(reply));
    };
    ws.onclose = (event) => {
      if (socket === ws) { socket = null; state = "JARVIS is not running"; }
      settle(opened && event.code === 1008 ? "wrong pairing code" : "no answer");
    };
    // JARVIS is on this computer, so it answers at once or not at all.
    setTimeout(() => { if (!settled) { try { ws.close(); } catch (_) {} settle("no answer"); } }, 1500);
  });
}

async function connect() {
  if (trying) { again = true; return; }
  if (socket && socket.readyState === WebSocket.OPEN) return;
  const code = await pairingCode();
  if (!code) { state = "not paired"; return; }
  trying = true;
  if (state !== "wrong pairing code" && state !== "JARVIS is not running") state = "connecting";
  try {
    let outcome = "no answer";
    const order = lastPort ? [lastPort, ...PORTS.filter((p) => p !== lastPort)] : PORTS;
    for (const port of order) {
      outcome = await attempt(port, code);
      if (outcome !== "no answer") break;
    }
    if (outcome === "wrong pairing code") state = "wrong pairing code";
    else if (outcome === "no answer") state = "JARVIS is not running";
  } finally {
    trying = false;
  }
  if (again) { again = false; connect(); }
}

// Chrome puts background workers to sleep. An alarm wakes this one every
// half minute to reconnect if needed; JARVIS's pings keep it awake while
// connected.
chrome.alarms.create("keep-connected", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.storage.onChanged.addListener((changes) => {
  if (changes.code) { if (socket) socket.close(); socket = null; state = "connecting"; connect(); }
});
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message === "status") { connect(); respond(state); }
});
connect();

// ---------------------------------------------------------------- commands

function tabInfo(tab) {
  return { id: tab.id, title: tab.title || "", url: tab.url || "", active: tab.active, window: tab.windowId };
}

function waitUntilLoaded(tabId, timeout = 20000) {
  return new Promise((resolve) => {
    const finish = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(timer); resolve(); };
    const listener = (id, change) => { if (id === tabId && change.status === "complete") finish(); };
    const timer = setTimeout(finish, timeout);  // slow pages: carry on with what has loaded
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then((tab) => { if (tab.status === "complete") finish(); }).catch(finish);
  });
}

async function chooseTab(tabId) {
  if (tabId != null) return chrome.tabs.get(tabId);
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!active) throw new Error("There is no open tab.");
  return active;
}

// Run one of the page.js functions inside the page.
async function inPage(tab, func, args = []) {
  if (!/^https?:|^file:/.test(tab.url || "")) {
    throw new Error("This kind of page (a browser settings page, a new tab, or the extension store) cannot be read or controlled.");
  }
  let frame;
  try {
    [frame] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func, args });
  } catch (error) {
    if (/error page/i.test(String(error))) throw new Error("The page could not be loaded. The site may be down, or the address may be wrong.");
    throw error;
  }
  if (!frame) throw new Error("The page did not respond.");
  if (frame.result && frame.result.error) throw new Error(frame.result.error);
  return frame.result;
}

async function run(action, args) {
  if (action === "tabs") {
    return (await chrome.tabs.query({})).map(tabInfo);
  }
  if (action === "open") {
    let tab;
    if (args.new_tab === false) {
      tab = await chooseTab(args.tab);
      await chrome.tabs.update(tab.id, { url: args.url });
    } else {
      tab = await chrome.tabs.create({ url: args.url, active: args.background !== true });
    }
    await waitUntilLoaded(tab.id);
    return tabInfo(await chrome.tabs.get(tab.id));
  }
  if (action === "focus") {
    const tab = await chooseTab(args.tab);
    await chrome.tabs.update(tab.id, { active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
    return tabInfo(await chrome.tabs.get(tab.id));
  }
  if (action === "close") {
    const tab = await chooseTab(args.tab);
    await chrome.tabs.remove(tab.id);
    return { closed: tabInfo(tab) };
  }

  const tab = await chooseTab(args.tab);
  if (action === "read") {
    const page = await inPage(tab, jarvisReadPage);
    return { tab: tabInfo(await chrome.tabs.get(tab.id)), ...page };
  }
  if (action === "click" || action === "type" || action === "select" || action === "scroll" || action === "key") {
    const before = tab.url;
    const done = await inPage(tab, jarvisAct, [action, args]);
    // A click may load a new page; give it a moment, then report where we are.
    await new Promise((resolve) => setTimeout(resolve, 400));
    let now = await chrome.tabs.get(tab.id);
    if (now.status === "loading" || now.url !== before) { await waitUntilLoaded(tab.id, 10000); now = await chrome.tabs.get(tab.id); }
    return { ...done, tab: tabInfo(now), navigated: now.url !== before };
  }
  throw new Error(`Unknown command: ${action}`);
}
