let lastState = "";
let pendingTimer = null;

function readPageState() {
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
}

function reportPageState() {
  pendingTimer = null;
  const page = readPageState();
  const state = JSON.stringify(page);
  if (state === lastState && !page.hasEditor) return;
  lastState = state;
  chrome.runtime.sendMessage({type: "gemini-cookie-refresh-page", page});
}

function scheduleReport() {
  if (pendingTimer !== null) return;
  pendingTimer = setTimeout(reportPageState, 500);
}

new MutationObserver(scheduleReport).observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
});
document.addEventListener("visibilitychange", scheduleReport);
scheduleReport();
