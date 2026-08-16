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

  // --- Fetch and Load JSON from Google Tasks ---
  async function loadJsonExport() {
    jsonStatusMsg.textContent = 'JSON ophalen vanuit Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    syncBadge.textContent = 'Laden...';
    
    try {
      const res = await fetch(`${rootPath}/api/json/export`);
      if (!res.ok) throw new Error('Kon JSON niet ophalen');
      currentJsonData = await res.json();
      
      const formatted = JSON.stringify(currentJsonData, null, 2);
      jsonTextarea.value = formatted;

      const totalLists = currentJsonData.totaal_lijsten || 0;
      const totalTasks = currentJsonData.totaal_taken || 0;
      jsonStatsTag.textContent = `${totalTasks} taken in ${totalLists} lijsten`;
      jsonStatusMsg.textContent = `✓ Geladen: ${totalTasks} taken in ${totalLists} lijsten.`;
      jsonStatusMsg.className = 'status-msg success';
      syncBadge.textContent = 'Klaar';
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Fout bij ophalen JSON: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      syncBadge.textContent = 'Fout';
    }
  }

  // --- 1. Kopieer JSON knop ---
  btnCopyJson.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(jsonTextarea.value);
      showToast('JSON gekopieerd naar klembord! 📋');
    } catch (e) {
      jsonTextarea.select();
      document.execCommand('copy');
      showToast('JSON gekopieerd! 📋');
    }
  });

  // --- 2. Plak JSON knop ---
  btnPasteJson.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text || !text.trim()) {
        showToast('Klembord is leeg', true);
        return;
      }
      try {
        const parsed = JSON.parse(text);
        jsonTextarea.value = JSON.stringify(parsed, null, 2);
        jsonStatusMsg.textContent = '✓ JSON geplakt en geformatteerd vanaf klembord!';
        jsonStatusMsg.className = 'status-msg success';
        showToast('JSON geplakt vanaf klembord! 📋');
      } catch (err) {
        jsonTextarea.value = text;
        jsonStatusMsg.textContent = '⚠ Geplakte tekst is geen geldige JSON: ' + err.message;
        jsonStatusMsg.className = 'status-msg error';
        showToast('Let op: Geplakte tekst bevat syntaxfouten', true);
      }
    } catch (e) {
      // Fallback focus to textarea
      jsonTextarea.focus();
      showToast('Plak direct met Ctrl+V / Cmd+V in het tekstveld');
    }
  });

  // --- 3. Herlaad knop ---
  btnReloadJson.addEventListener('click', () => {
    loadJsonExport();
    showToast('JSON herladen vanuit Google');
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
      return;
    }

    btnApplyJson.disabled = true;
    btnSyncNow.disabled = true;
    syncBadge.textContent = 'Syncen...';
    syncBadge.className = 'badge syncing';
    jsonStatusMsg.textContent = 'Bezig met toepassen en synchroniseren naar Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    showToast('Bezig met synchroniseren naar Google Tasks...');

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
        setTimeout(loadJsonExport, 1000);
      } else {
        throw new Error(result.error || 'Onbekende fout');
      }
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Fout bij synchroniseren: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      syncBadge.textContent = 'Fout';
      syncBadge.className = 'badge';
      showToast('Fout bij syncen: ' + e.message, true);
    } finally {
      btnApplyJson.disabled = false;
      btnSyncNow.disabled = false;
    }
  }

  btnApplyJson.addEventListener('click', applyChanges);
  btnSyncNow.addEventListener('click', applyChanges);

  // Initial load
  loadJsonExport();
});
