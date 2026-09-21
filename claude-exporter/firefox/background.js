// Handle extension installation
chrome.runtime.onInstalled.addListener(() => {
  console.log('Claude Conversation Exporter installed');
});

// Inject content script into already-open Claude.ai tabs when extension is installed/updated
chrome.runtime.onInstalled.addListener(() => {
  chrome.tabs.query({ url: 'https://claude.ai/*' }, (tabs) => {
    tabs.forEach(tab => {
      const files = ['jszip.min.js', 'utils.js', 'content.js'];
      files.forEach(file => {
        chrome.tabs.executeScript(tab.id, { file }, () => {
          if (chrome.runtime.lastError) {
            console.log('Could not inject', file, 'into tab', tab.id, chrome.runtime.lastError.message);
          }
        });
      });
    });
  });
});

// Handle messages from popup when content script might not be injected
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'ensureContentScript') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        const files = ['jszip.min.js', 'utils.js', 'content.js'];
        let injected = 0;
        files.forEach(file => {
          chrome.tabs.executeScript(tabs[0].id, { file }, () => {
            injected++;
            if (injected === files.length) {
              sendResponse({ success: true });
            }
          });
        });
      }
    });
    return true;
  }
});
