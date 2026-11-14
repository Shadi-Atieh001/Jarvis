const status = document.getElementById("status"), code = document.getElementById("code");

function show(state) {
  const text = {
    "connected": "Connected to JARVIS.",
    "connecting": "Connecting…",
    "not paired": "Not paired yet. Paste the pairing code below.",
    "wrong pairing code": "JARVIS did not accept that pairing code.",
    "JARVIS is not running": "JARVIS is not running on this computer.",
  }[state] || state;
  status.textContent = text;
  status.className = state === "connected" ? "good" : "bad";
}
function refresh() { chrome.runtime.sendMessage("status", (state) => show(state || "JARVIS is not running")); }

document.getElementById("save").onclick = async () => {
  await chrome.storage.local.set({ code: code.value.trim() });
  code.value = "";
  show("connecting");
  setTimeout(refresh, 1200);
};
refresh();
setInterval(refresh, 2000);
