// Capture unhandled errors for diagnostics (sanitized, stored in chrome.storage.local)
if (typeof initErrorCapture === 'function') initErrorCapture('popup');

// Get organization ID from storage (fallback)
async function getStoredOrgId() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(['organizationId'], (result) => {
      resolve(result.organizationId);
    });
  });
}

// Auto-detect organization ID via content script, fall back to stored
async function getOrgId() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url && tab.url.includes('claude.ai')) {
      const response = await new Promise((resolve) => {
        chrome.tabs.sendMessage(tab.id, { action: 'detectOrgId' }, (res) => {
          if (chrome.runtime.lastError) {
            resolve(null);
          } else {
            resolve(res);
          }
        });
      });
      if (response && response.success && response.orgId) {
        // Save for future use / fallback
        chrome.storage.sync.set({ organizationId: response.orgId });
        return response.orgId;
      }
    }
  } catch (e) {
    console.log('Auto-detect org ID failed, falling back to stored:', e);
  }
  // Fall back to stored org ID
  return getStoredOrgId();
}

document.addEventListener('DOMContentLoaded', async () => {
  // Pull the popup title + version from the manifest so the testing branch
  // shows "Claude Exporter Beta" without a separate HTML edit.
  const manifest = chrome.runtime.getManifest();
  document.getElementById('header-title').textContent = manifest.name;
  document.getElementById('header-version').textContent = `v${manifest.version}`;

  // Handle checkbox dependencies
  const includeChatsCheckbox = document.getElementById('includeChats');
  const includeThinkingCheckbox = document.getElementById('includeThinking');
  const includeMetadataCheckbox = document.getElementById('includeMetadata');
  const includeArtifactsCheckbox = document.getElementById('includeArtifacts');

  function updateCheckboxStates() {
    const chatsEnabled = includeChatsCheckbox.checked;

    // Disable thinking, metadata and inline artifacts when chats is unchecked
    includeThinkingCheckbox.disabled = !chatsEnabled;
    includeMetadataCheckbox.disabled = !chatsEnabled;
    includeArtifactsCheckbox.disabled = !chatsEnabled;

    // Optionally uncheck them when disabled
    if (!chatsEnabled) {
      includeThinkingCheckbox.checked = false;
      includeMetadataCheckbox.checked = false;
      includeArtifactsCheckbox.checked = false;
    }
  }

  includeChatsCheckbox.addEventListener('change', updateCheckboxStates);
  updateCheckboxStates(); // Initialize on load
});

  // Get current conversation ID from URL
  async function getCurrentConversationId() {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    const url = new URL(tab.url);
    const match = url.pathname.match(/\/chat\/([a-f0-9-]+)/);
    return match ? match[1] : null;
  }
  
  // Show status message
  function showStatus(message, type = 'info') {
    const statusEl = document.getElementById('status');
    statusEl.className = `status ${type}`;

    // Swap "Options" for a clickable link when the message points users to the options page
    if (type === 'error' && message.includes('Please set this value in Options.')) {
      const linked = message.replace('Options.', '<a href="#" id="statusOpenOptions">Options</a>.');
      statusEl.innerHTML = linked;
      document.getElementById('statusOpenOptions').addEventListener('click', (e) => {
        e.preventDefault();
        chrome.runtime.openOptionsPage();
      });
    } else if (type === 'error' && (message.includes('403') || message.includes('404'))) {
      // Legacy 403/404 hint
      statusEl.innerHTML = `${message}<br>Is your <a href="#" id="statusOpenOptions">Organization ID</a> correct?`;
      document.getElementById('statusOpenOptions').addEventListener('click', (e) => {
        e.preventDefault();
        chrome.runtime.openOptionsPage();
      });
    } else {
      statusEl.textContent = message;
    }

    if (type === 'success') {
      setTimeout(() => {
        statusEl.textContent = '';
        statusEl.className = '';
      }, 3000);
    }
  }
  
  // Export current conversation
document.getElementById('exportCurrent').addEventListener('click', async () => {
  const button = document.getElementById('exportCurrent');
  button.disabled = true;
  showStatus('Fetching conversation...', 'info');
  
  try {
    const orgId = await getOrgId();
    const conversationId = await getCurrentConversationId();
    
    if (!orgId) {
      throw new Error('Failed to obtain organization ID: Please set this value in Options.');
    }
    if (!conversationId) {
      throw new Error('Could not detect conversation ID. Make sure you are on a claude.ai conversation page.');
    }

    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    
    // Check if we're on claude.ai
    if (!tab.url.includes('claude.ai')) {
      throw new Error('Please navigate to a claude.ai conversation page first.');
    }
      
          chrome.tabs.sendMessage(tab.id, {
      action: 'exportConversation',
      conversationId,
      orgId,
      format: document.getElementById('format').value,
      includeChats: document.getElementById('includeChats').checked,
      includeThinking: document.getElementById('includeThinking').checked,
      includeMetadata: document.getElementById('includeMetadata').checked,
      includeArtifacts: document.getElementById('includeArtifacts').checked,
      extractArtifacts: document.getElementById('extractArtifacts').checked,
      artifactFormat: document.getElementById('artifactFormat').value,
      flattenArtifacts: document.getElementById('flattenArtifacts').checked
    }, (response) => {
      if (chrome.runtime.lastError) {
        console.error('Chrome runtime error:', chrome.runtime.lastError);
        showStatus(`Error: ${chrome.runtime.lastError.message}`, 'error');
        button.disabled = false;
        return;
      }
      
      if (response?.success) {
        showStatus('Conversation exported successfully!', 'success');
      } else {
        const errorMsg = response?.error || 'Export failed';
        console.error('Export failed:', errorMsg, response?.details);
        showStatus(errorMsg, 'error');
      }
      button.disabled = false;
    });
    } catch (error) {
      showStatus(error.message, 'error');
      button.disabled = false;
    }
  });
  
  // Browse conversations
  document.getElementById('browseConversations').addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('browse.html') });
  });

  async function runBulkExport(button, exportOptions, statusMessage = 'Fetching all conversations...') {
    button.disabled = true;
    showStatus(statusMessage, 'info');

    try {
      const orgId = await getOrgId();

      if (!orgId) {
        throw new Error('Failed to obtain organization ID: Please set this value in Options.');
      }

      const [tab] = await browser.tabs.query({ active: true, currentWindow: true });

      chrome.tabs.sendMessage(tab.id, {
        action: 'exportAllConversations',
        orgId,
        ...exportOptions,
      }, (response) => {
        if (chrome.runtime.lastError) {
          console.error('Chrome runtime error:', chrome.runtime.lastError);
          showStatus(`Error: ${chrome.runtime.lastError.message}`, 'error');
          button.disabled = false;
          return;
        }

        if (response?.success) {
          if (response.warnings) {
            showStatus(response.warnings, 'info');
          } else {
            showStatus(`Exported ${response.count} conversations!`, 'success');
          }
        } else {
          const errorMsg = response?.error || 'Export failed';
          console.error('Export failed:', errorMsg, response?.details);
          showStatus(errorMsg, 'error');
        }
        button.disabled = false;
      });
    } catch (error) {
      showStatus(error.message, 'error');
      button.disabled = false;
    }
  }

  function getExportOptionsFromUI() {
    return {
      format: document.getElementById('format').value,
      includeChats: document.getElementById('includeChats').checked,
      includeMetadata: document.getElementById('includeMetadata').checked,
      includeArtifacts: document.getElementById('includeArtifacts').checked,
      extractArtifacts: document.getElementById('extractArtifacts').checked,
      artifactFormat: document.getElementById('artifactFormat').value,
      flattenArtifacts: document.getElementById('flattenArtifacts').checked,
    };
  }

  // Export all conversations
  document.getElementById('exportAll').addEventListener('click', () => {
    runBulkExport(document.getElementById('exportAll'), getExportOptionsFromUI());
  });

  // Export for Obsidian — fixed JSON / flat root layout for vault import
  document.getElementById('exportForObsidian').addEventListener('click', () => {
    runBulkExport(
      document.getElementById('exportForObsidian'),
      OBSIDIAN_EXPORT_OPTIONS,
      'Preparing Obsidian export...'
    );
  });