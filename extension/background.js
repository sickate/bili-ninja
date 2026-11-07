import { tabState } from "./tab-state.js";

const queues = new Map();
// Register listeners synchronously, including when the service worker wakes up.
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url || change.status === "complete") void syncTab(tabId);
});
chrome.tabs.onActivated.addListener(({ tabId }) => { void syncTab(tabId); });
chrome.tabs.onRemoved.addListener(tabId => { queues.delete(tabId); });
chrome.runtime.onInstalled.addListener(() => { void refreshTabs(); });
chrome.runtime.onStartup.addListener(() => { void refreshTabs(); });

// Chrome opens the panel directly from the icon click, retaining the user gesture.
// No popup or new browser tab is created.
const ready = Promise.all([
  chrome.action.disable(),
  chrome.sidePanel.setOptions({ enabled: false }),
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }),
  chrome.declarativeNetRequest.updateSessionRules({
    removeRuleIds: [1],
    addRules: [{
      id: 1,
      priority: 1,
      action: {
        type: "modifyHeaders",
        requestHeaders: [{ header: "Referer", operation: "set", value: "https://www.bilibili.com/" }],
      },
      condition: {
        initiatorDomains: [chrome.runtime.id],
        requestDomains: ["bilivideo.com", "bilivideo.cn", "bilivideo.tv"],
        resourceTypes: ["xmlhttprequest"],
      },
    }],
  }),
]);

export function syncTab(tabId) {
  // Serialize changes per tab and read its latest URL. An older update must not
  // re-enable a panel after the tab has already left Bilibili.
  const operation = (queues.get(tabId) || Promise.resolve()).then(async () => {
    await ready;
    const tab = await chrome.tabs.get(tabId);
    const state = tabState(tabId, tab.url);
    const current = await chrome.sidePanel.getOptions({ tabId });
    if (current.enabled !== state.enabled || (state.enabled && current.path !== state.path)) {
      await chrome.sidePanel.setOptions({ tabId, enabled: state.enabled, ...(state.enabled ? { path: state.path } : {}) });
    }
    await Promise.all([
      chrome.action.setIcon({ tabId, path: state.icon }),
      chrome.action.setTitle({ tabId, title: state.title }),
      state.enabled ? chrome.action.enable(tabId) : chrome.action.disable(tabId),
    ]);
  }).catch(error => {
    if (!/No tab|Invalid tab|closed|removed/i.test(error.message)) console.warn("Bili Ninja:", error.message);
  });
  queues.set(tabId, operation);
  void operation.then(() => { if (queues.get(tabId) === operation) queues.delete(tabId); });
  return operation;
}

async function refreshTabs() {
  await ready;
  const tabs = await chrome.tabs.query({});
  await Promise.all(tabs.filter(tab => tab.id !== undefined).map(tab => syncTab(tab.id)));
}

export const initialized = refreshTabs().catch(error => console.warn("Bili Ninja:", error.message));
