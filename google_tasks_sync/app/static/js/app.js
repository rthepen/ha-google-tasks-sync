document.addEventListener('DOMContentLoaded', () => {
  const rootPath = document.body.dataset.rootPath || '';
  
  // State
  let currentJsonData = null;

  // DOM Elements
  const btnSyncNow = document.getElementById('btn-sync-now');
  const syncBadge = document.getElementById('sync-status-badge');
  const jsonTextarea = document.getElementById('json-textarea');
  const jsonStatusMsg = document.getElementById('json-status-msg');
  const jsonStatsTag = document.getElementById('json-stats-tag');
  
  const btnCopyJson = document.getElementById('btn-copy-json');
  const btnPasteJson = document.getElementById('btn-paste-json');
  const btnReloadJson = document.getElementById('btn-reload-json');
  const btnApplyJson = document.getElementById('btn-apply-json');

  // Debug elements
  const logsContainer = document.getElementById('logs-container');
  const debugLastSync = document.getElementById('debug-last-sync');
  const btnClearLogs = document.getElementById('btn-clear-logs');
  const btnRefreshLogs = document.getElementById('btn-refresh-logs');

  // Toast
  const toast = document.getElementById('toast');

  function showToast(message, isError = false) {
    toast.textContent = message;
    toast.style.background = isError ? '#da3633' : '#1f6feb';
    toast.classList.add('show');
    setTimeout(() => {
      toast.classList.remove('show');
    }, 3000);
  }

  function appendClientLog(msg, level = 'info') {
    const time = new Date().toTimeString().split(' ')[0];
    const el = document.createElement('div');
    el.className = `log-entry level-${level}`;
    el.textContent = `[${time}] [CLIENT-${level.toUpperCase()}] ${msg}`;
    logsContainer.prepend(el);
  }

  // --- Fetch Logs and Status from Server ---
  async function loadLogsAndStatus() {
    try {
      const res = await fetch(`${rootPath}/api/status`);
      if (!res.ok) return;
      const data = await res.json();

      debugLastSync.textContent = `Laatste sync: ${data.last_sync_time || 'Nog niet'}`;

      if (data.logs && data.logs.length > 0) {
        logsContainer.innerHTML = data.logs.map(l => 
          `<div class="log-entry level-${l.level}">[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}</div>`
        ).join('');
      } else {
        logsContainer.innerHTML = '<div class="log-entry">[SYSTEM] Geen recente server logs.</div>';
      }
    } catch (e) {
      appendClientLog('Fout bij ophalen server logs: ' + e.message, 'error');
    }
  }

  btnClearLogs.addEventListener('click', () => {
    logsContainer.innerHTML = '<div class="log-entry">[SYSTEM] Logboek gewist.</div>';
    showToast('Logboek gewist');
  });

  btnRefreshLogs.addEventListener('click', () => {
    loadLogsAndStatus();
    showToast('Logs ververst');
  });

  // --- Handle Tab Key in Textarea ---
  jsonTextarea.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = jsonTextarea.selectionStart;
      const end = jsonTextarea.selectionEnd;
      jsonTextarea.value = jsonTextarea.value.substring(0, start) + '  ' + jsonTextarea.value.substring(end);
      jsonTextarea.selectionStart = jsonTextarea.selectionEnd = start + 2;
    }
  });

  // --- Real-time Syntax Feedback on Typing ---
  jsonTextarea.addEventListener('input', () => {
    try {
      const parsed = JSON.parse(jsonTextarea.value);
      const totalLists = parsed.lijsten ? parsed.lijsten.length : (parsed.total_hoofdtaken || 'meerdere');
      jsonStatusMsg.textContent = `✓ Geldige JSON (${totalLists} lijsten). Klaar om toe te passen.`;
      jsonStatusMsg.className = 'status-msg success';
    } catch (err) {
      jsonStatusMsg.textContent = `⚠ Bezig met typen: ${err.message}`;
      jsonStatusMsg.className = 'status-msg error';
    }
  });

  // --- Fetch and Load JSON from Google Tasks ---
  async function loadJsonExport() {
    jsonStatusMsg.textContent = 'JSON ophalen vanuit Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    syncBadge.textContent = 'Laden...';
    appendClientLog('Ophalen van taken JSON vanuit backend...');
    
    try {
      const res = await fetch(`${rootPath}/api/json/export`);
      if (!res.ok) throw new Error('Kon JSON niet ophalen');
      currentJsonData = await res.json();
      
      const formatted = JSON.stringify(currentJsonData, null, 2);
      jsonTextarea.value = formatted;
      jsonTextarea.scrollTop = 0; // Scroll to top initially

      const totalLists = currentJsonData.totaal_lijsten || 0;
      const totalTasks = currentJsonData.totaal_taken || 0;
      jsonStatsTag.textContent = `${totalTasks} taken in ${totalLists} lijsten`;
      jsonStatusMsg.textContent = `✓ Geladen: ${totalTasks} taken in ${totalLists} lijsten.`;
      jsonStatusMsg.className = 'status-msg success';
      syncBadge.textContent = 'Klaar';
      appendClientLog(`JSON succesvol ingeladen: ${totalTasks} taken verdeeld over ${totalLists} lijsten.`, 'success');
      loadLogsAndStatus();
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Fout bij ophalen JSON: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      syncBadge.textContent = 'Fout';
      appendClientLog('Fout bij inladen JSON: ' + e.message, 'error');
    }
  }

  // --- 1. Kopieer JSON knop ---
  btnCopyJson.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(jsonTextarea.value);
      showToast('JSON gekopieerd naar klembord! 📋');
      appendClientLog('JSON gekopieerd naar klembord.', 'info');
    } catch (e) {
      jsonTextarea.select();
      document.execCommand('copy');
      showToast('JSON gekopieerd! 📋');
      appendClientLog('JSON gekopieerd via fallback select.', 'info');
    }
  });

  // --- 2. Plak JSON knop ---
  btnPasteJson.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text || !text.trim()) {
        showToast('Klembord is leeg', true);
        appendClientLog('Plakken mislukt: klembord is leeg.', 'warning');
        return;
      }
      try {
        const parsed = JSON.parse(text);
        jsonTextarea.value = JSON.stringify(parsed, null, 2);
        jsonStatusMsg.textContent = '✓ JSON geplakt en geformatteerd vanaf klembord!';
        jsonStatusMsg.className = 'status-msg success';
        showToast('JSON geplakt vanaf klembord! 📋');
        appendClientLog('Geldige JSON geplakt vanaf klembord.', 'success');
      } catch (err) {
        jsonTextarea.value = text;
        jsonStatusMsg.textContent = '⚠ Geplakte tekst is geen geldige JSON: ' + err.message;
        jsonStatusMsg.className = 'status-msg error';
        showToast('Let op: Geplakte tekst bevat syntaxfouten', true);
        appendClientLog('Geplakte JSON bevat syntaxfout: ' + err.message, 'error');
      }
    } catch (e) {
      jsonTextarea.focus();
      showToast('Plak direct met Ctrl+V / Cmd+V in het tekstveld');
      appendClientLog('Direct plakken vereist (toegang geweigerd door browser).', 'warning');
    }
  });

  // --- 3. Herlaad knop ---
  btnReloadJson.addEventListener('click', () => {
    loadJsonExport();
    showToast('JSON herladen vanuit Google');
    appendClientLog('Herladen vanuit Google Tasks getriggerd.');
  });

  // --- 4. Toepassen / Syncen naar Google Tasks ---
  async function applyChanges() {
    let parsed;
    try {
      parsed = JSON.parse(jsonTextarea.value);
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Ongeldige JSON syntax: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      showToast('Kan niet toepassen: ongeldige JSON!', true);
      appendClientLog('Toepassen geannuleerd: ongeldige JSON syntax: ' + e.message, 'error');
      return;
    }

    btnApplyJson.disabled = true;
    btnSyncNow.disabled = true;
    syncBadge.textContent = 'Syncen...';
    syncBadge.className = 'badge syncing';
    jsonStatusMsg.textContent = 'Bezig met toepassen en synchroniseren naar Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    showToast('Bezig met synchroniseren naar Google Tasks...');
    appendClientLog('Start synchronisatie van gewijzigde JSON naar Google Tasks...', 'info');

    try {
      const res = await fetch(`${rootPath}/api/json/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ json_data: parsed })
      });
      const result = await res.json();
      if (result.success) {
        showToast('Taken succesvol gesynchroniseerd met Google Tasks! 🚀');
        jsonStatusMsg.textContent = '✓ Succesvol gesynchroniseerd met Google Tasks!';
        jsonStatusMsg.className = 'status-msg success';
        syncBadge.textContent = 'Klaar';
        syncBadge.className = 'badge';
        appendClientLog('Google Tasks API import succesvol afgerond: ' + JSON.stringify(result.results), 'success');
        setTimeout(() => {
          loadJsonExport();
          loadLogsAndStatus();
        }, 1000);
      } else {
        throw new Error(result.error || 'Onbekende fout');
      }
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Fout bij synchroniseren: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      syncBadge.textContent = 'Fout';
      syncBadge.className = 'badge';
      showToast('Fout bij syncen: ' + e.message, true);
      appendClientLog('Synchronisatiefout: ' + e.message, 'error');
    } finally {
      btnApplyJson.disabled = false;
      btnSyncNow.disabled = false;
    }
  }

  btnApplyJson.addEventListener('click', applyChanges);
  btnSyncNow.addEventListener('click', applyChanges);

  // Initial load
  loadJsonExport();
  loadLogsAndStatus();
  setInterval(loadLogsAndStatus, 10000); // Polling logs every 10s
});
