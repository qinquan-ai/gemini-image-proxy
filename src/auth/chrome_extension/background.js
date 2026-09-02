const BRIDGE_ORIGIN = "http://127.0.0.1:4982";
const BRIDGE_CLIENT = "gemini-cookie-refresh-extension-v1";
const DEFAULT_GEMINI_URL = "https://gemini.google.com/app";
const POLL_ALARM = "gemini-cookie-refresh-poll";

let activeRun = null;
let captureComplete = false;
let openingGemini = false;

function isGeminiUrl(url) {
  return typeof url === "string" && url.startsWith("https://gemini.google.com/");
}

async function getActiveRun() {
  try {
    const response = await fetch(`${BRIDGE_ORIGIN}/status`, {
      cache: "no-store",
      headers: {"X-Gemini-Cookie-Bridge": BRIDGE_CLIENT},
    });
    if (!response.ok) return null;
    const status = await response.json();
    if (!status.active || !status.token) return null;
    return status;
  } catch (_error) {
    return null;
  }
}

async function inspectGeminiTab(tabId) {
  if (!activeRun || captureComplete) return;

  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch (_error) {
    return;
  }
  if (!isGeminiUrl(tab.url)) return;

  let page;
  try {
    const result = await chrome.scripting.executeScript({
      target: {tabId},
      func: () => {
        const editor = document.querySelector([
          "rich-textarea .ql-editor",
          "rich-textarea [contenteditable='true']",
          "div[contenteditable='true'][role='textbox']",
          "textarea[aria-label*='prompt' i]",
        ].join(","));
        const signIn = Array.from(document.querySelectorAll("a,button")).some(element => {
          const label = `${element.getAttribute("aria-label") || ""} ${element.textContent || ""}`;
          return /sign in|log in|登录|登入/i.test(label);
        });
        return {hasEditor: Boolean(editor), hasSignIn: signIn};
      },
    });
    page = result[0]?.result;
  } catch (_error) {
    return;
  }
  if (!page?.hasEditor || page.hasSignIn) return;

  let cookies;
  try {
    cookies = await chrome.cookies.getAll({domain: "google.com"});
  } catch (_error) {
    return;
  }
  const hasAuthCookie = cookies.some(cookie =>
    (cookie.name === "__Secure-1PSID" || cookie.name === "SID") && cookie.value
  );
  if (!hasAuthCookie) return;

  try {
    const response = await fetch(`${BRIDGE_ORIGIN}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gemini-Cookie-Bridge": BRIDGE_CLIENT,
        "X-Gemini-Cookie-Bridge-Token": activeRun.token,
      },
      body: JSON.stringify({cookies, url: tab.url, page}),
    });
    if (response.ok) captureComplete = true;
  } catch (_error) {
    // The updater may have stopped between status and capture. A later run retries.
  }
}

async function captureFromPageMessage(tabId, page) {
  if (!activeRun) await activateBridge();
  if (!activeRun || captureComplete || !page?.hasEditor || page.hasSignIn) return;

  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch (_error) {
    return;
  }
  if (!isGeminiUrl(tab.url)) return;

  let cookies;
  try {
    cookies = await chrome.cookies.getAll({domain: "google.com"});
  } catch (_error) {
    return;
  }
  const hasAuthCookie = cookies.some(cookie =>
    (cookie.name === "__Secure-1PSID" || cookie.name === "SID") && cookie.value
  );
  if (!hasAuthCookie) return;

  try {
    const response = await fetch(`${BRIDGE_ORIGIN}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Gemini-Cookie-Bridge": BRIDGE_CLIENT,
        "X-Gemini-Cookie-Bridge-Token": activeRun.token,
      },
      body: JSON.stringify({cookies, url: tab.url, page}),
    });
    if (response.ok) captureComplete = true;
  } catch (_error) {
    // A later page-state message retries while the updater is active.
  }
}

function scheduleInspection(tabId) {
  for (const delay of [500, 1500, 3500, 7000, 15000]) {
    setTimeout(() => inspectGeminiTab(tabId), delay);
  }
}

async function ensureGeminiTab(url) {
  if (openingGemini || captureComplete) return;
  openingGemini = true;
  try {
    const tabs = await chrome.tabs.query({});
    const existing = tabs.find(tab => isGeminiUrl(tab.url));
    const tab = existing
      ? await chrome.tabs.update(existing.id, {active: true})
      : await chrome.tabs.create({url, active: true});
    scheduleInspection(tab.id);
  } finally {
    openingGemini = false;
  }
}

async function activateBridge() {
  const run = await getActiveRun();
  if (!run) {
    activeRun = null;
    captureComplete = false;
    return;
  }
  if (activeRun?.token !== run.token) {
    activeRun = run;
    captureComplete = false;
  }
  await ensureGeminiTab(run.geminiUrl || DEFAULT_GEMINI_URL);
}

chrome.runtime.onInstalled.addListener(activateBridge);
chrome.runtime.onStartup.addListener(activateBridge);
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== "gemini-cookie-refresh-page" || !sender.tab?.id) return;
  captureFromPageMessage(sender.tab.id, message.page);
});
chrome.windows.onCreated.addListener(() => setTimeout(activateBridge, 300));
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!isGeminiUrl(tab.url)) return;
  if (!activeRun) {
    activateBridge();
  } else if (changeInfo.status === "complete" || changeInfo.url) {
    scheduleInspection(tabId);
  }
});
chrome.tabs.onActivated.addListener(async ({tabId}) => {
  if (!activeRun) {
    await activateBridge();
    return;
  }
  scheduleInspection(tabId);
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === POLL_ALARM) activateBridge();
});

chrome.alarms.create(POLL_ALARM, {periodInMinutes: 0.5});
activateBridge();
