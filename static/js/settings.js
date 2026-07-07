const form = document.getElementById('llm-settings-form');
const baseUrlInput = document.getElementById('settings-base-url');
const apiKeyInput = document.getElementById('settings-api-key');
const modelInput = document.getElementById('settings-model-input');
const keyState = document.getElementById('settings-key-state');
const status = document.getElementById('settings-status');
const saveButton = document.getElementById('settings-save');

function showStatus(message, kind = '') {
  status.textContent = message;
  status.className = kind;
}

async function loadSettings() {
  try {
    const response = await fetch('/api/settings/llm');
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '读取失败');
    const settings = data.settings;
    baseUrlInput.value = settings.base_url || '';
    modelInput.value = settings.model || '';
    keyState.textContent = settings.api_key_configured
      ? `当前 Key：${settings.api_key_masked}；留空不会覆盖`
      : '当前未配置 API Key';
  } catch (error) {
    showStatus(`读取失败：${error.message}`, 'error');
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  saveButton.disabled = true;
  showStatus('保存中...');
  try {
    const payload = {
      base_url: baseUrlInput.value.trim(),
      model: modelInput.value.trim(),
    };
    if (apiKeyInput.value.trim()) payload.api_key = apiKeyInput.value.trim();
    const response = await fetch('/api/settings/llm', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '保存失败');
    apiKeyInput.value = '';
    showStatus('已保存到 .env，重启 Ward 后生效。', 'success');
  } catch (error) {
    showStatus(`保存失败：${error.message}`, 'error');
  } finally {
    saveButton.disabled = false;
  }
});

loadSettings();
