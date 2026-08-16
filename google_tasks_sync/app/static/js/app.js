document.addEventListener('DOMContentLoaded', () => {
  const rootPath = document.body.dataset.rootPath || '';
  
  // State
  let currentJsonData = null;
  let allAccounts = [];
  let isSyncing = false;

  // DOM Elements
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');
  const btnSyncNow = document.getElementById('btn-sync-now');
  const syncBadge = document.getElementById('sync-status-badge');
  const logsContainer = document.getElementById('logs-container');
  
  // Stats
  const statAccounts = document.getElementById('stat-accounts');
  const statTasks = document.getElementById('stat-tasks');
  const statLastSync = document.getElementById('stat-last-sync');
  const statSyncStatus = document.getElementById('stat-sync-status');
  
  // JSON Editor Elements
  const jsonTextarea = document.getElementById('json-textarea');
  const jsonStatusMsg = document.getElementById('json-status-msg');
  const jsonStatsTag = document.getElementById('json-stats-tag');
  const btnCopyJson = document.getElementById('btn-copy-json');
  const btnDownloadJson = document.getElementById('btn-download-json');
  const btnReloadJson = document.getElementById('btn-reload-json');
  const btnValidateJson = document.getElementById('btn-validate-json');
  const btnApplyJson = document.getElementById('btn-apply-json');

  // Tasks View
  const listsCardsContainer = document.getElementById('lists-cards-container');
  const taskSearchInput = document.getElementById('task-search-input');

  // Accounts View
  const accountsListContainer = document.getElementById('accounts-list-container');
  const btnOpenAddAccount = document.getElementById('btn-open-add-account');
  const modalAddAccount = document.getElementById('modal-add-account');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnCancelAddAccount = document.getElementById('btn-cancel-add-account');
  const btnSaveAccount = document.getElementById('btn-save-account');
  const oauthStatusBox = document.getElementById('oauth-status-text');

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

  // --- Tab Switching ---
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const tabId = btn.dataset.tab;
      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const activeContent = document.getElementById(`tab-${tabId}`);
      if (activeContent) activeContent.classList.add('active');

      if (tabId === 'json-editor' && !jsonTextarea.value) {
        loadJsonExport();
      } else if (tabId === 'tasks-view') {
        renderTasksView();
      } else if (tabId === 'accounts') {
        loadAccounts();
      }
    });
  });

  // --- Fetch Status & Dashboard ---
  async function loadStatus() {
    try {
      const res = await fetch(`${rootPath}/api/status`);
      if (!res.ok) return;
      const data = await res.json();

      statAccounts.textContent = data.total_accounts || 0;
      statLastSync.textContent = data.last_sync_time || 'Nog niet';
      statSyncStatus.textContent = data.last_sync_status || 'Gereed';

      if (data.is_syncing) {
        syncBadge.textContent = 'Synchroniseren...';
        syncBadge.className = 'badge syncing';
        btnSyncNow.disabled = true;
      } else {
        syncBadge.textContent = 'Actief';
        syncBadge.className = 'badge';
        btnSyncNow.disabled = false;
      }

      // Render logs
      if (data.logs && data.logs.length > 0) {
        logsContainer.innerHTML = data.logs.map(l => 
          `<div class="log-entry level-${l.level}">[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}</div>`
        ).join('');
      } else {
        logsContainer.innerHTML = '<div class="log-entry">Geen recente logberichten.</div>';
      }
    } catch (e) {
      console.error('Error fetching status:', e);
    }
  }

  // --- Trigger Sync ---
  btnSyncNow.addEventListener('click', async () => {
    btnSyncNow.disabled = true;
    showToast('Synchronisatie gestart...');
    try {
      const res = await fetch(`${rootPath}/api/sync/now`, { method: 'POST' });
      const data = await res.json();
      showToast(data.status === 'success' ? 'Synchronisatie voltooid!' : 'Sync uitgevoerd: ' + (data.message || 'klaar'));
      loadStatus();
      loadJsonExport();
    } catch (e) {
      showToast('Fout bij starten synchronisatie', true);
    } finally {
      btnSyncNow.disabled = false;
    }
  });

  document.getElementById('btn-refresh-status').addEventListener('click', loadStatus);

  // --- JSON Editor Logic ---
  async function loadJsonExport() {
    jsonStatusMsg.textContent = 'JSON ophalen vanuit Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    try {
      const res = await fetch(`${rootPath}/api/json/export`);
      if (!res.ok) throw new Error('Kon JSON niet ophalen');
      currentJsonData = await res.json();
      
      const formatted = JSON.stringify(currentJsonData, null, 2);
      jsonTextarea.value = formatted;

      const totalLists = currentJsonData.totaal_lijsten || 0;
      const totalTasks = currentJsonData.totaal_taken || 0;
      statTasks.textContent = totalTasks;
      jsonStatsTag.textContent = `${totalTasks} taken in ${totalLists} lijsten`;
      jsonStatusMsg.textContent = `Succesvol geladen: ${totalTasks} taken in ${totalLists} lijsten.`;
      jsonStatusMsg.className = 'status-msg success';
    } catch (e) {
      jsonStatusMsg.textContent = 'Fout bij ophalen JSON: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
    }
  }

  // Copy JSON to Clipboard
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

  // Download JSON
  btnDownloadJson.addEventListener('click', () => {
    const blob = new Blob([jsonTextarea.value], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `google_tasks_export_${new Date().toISOString().slice(0,10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('JSON bestand gedownload! 📥');
  });

  // Reload JSON
  btnReloadJson.addEventListener('click', () => {
    loadJsonExport();
    showToast('JSON herladen vanuit Google');
  });

  // Validate JSON
  btnValidateJson.addEventListener('click', () => {
    try {
      const parsed = JSON.parse(jsonTextarea.value);
      const lists = parsed.lijsten || parsed.tasks || [];
      jsonStatusMsg.textContent = `✓ Geldige JSON! Bevat ${Array.isArray(lists) ? lists.length : 'meerdere'} lijsten/taken.`;
      jsonStatusMsg.className = 'status-msg success';
      showToast('JSON syntax is 100% correct! ✓');
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Ongeldige JSON: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      showToast('JSON bevat fouten!', true);
    }
  });

  // Apply JSON to Google Tasks
  btnApplyJson.addEventListener('click', async () => {
    let parsed;
    try {
      parsed = JSON.parse(jsonTextarea.value);
    } catch (e) {
      showToast('Kan niet toepassen: ongeldige JSON syntax!', true);
      return;
    }

    if (!confirm('Weet je zeker dat je deze gewijzigde JSON wilt toepassen op je Google Tasks accounts?')) {
      return;
    }

    btnApplyJson.disabled = true;
    jsonStatusMsg.textContent = 'Bezig met toepassen op Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    showToast('Bezig met bijwerken van Google Tasks...');

    try {
      const res = await fetch(`${rootPath}/api/json/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ json_data: parsed })
      });
      const result = await res.json();
      if (result.success) {
        showToast('Wijzigingen succesvol toegepast op Google Tasks! 🚀');
        jsonStatusMsg.textContent = '✓ Succesvol toegepast op Google Tasks!';
        jsonStatusMsg.className = 'status-msg success';
        loadStatus();
      } else {
        throw new Error(result.error || 'Onbekende fout');
      }
    } catch (e) {
      jsonStatusMsg.textContent = 'Fout bij toepassen: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      showToast('Fout bij toepassen: ' + e.message, true);
    } finally {
      btnApplyJson.disabled = false;
    }
  });

  // --- Tasks View Rendering ---
  async function renderTasksView() {
    if (!currentJsonData) {
      await loadJsonExport();
    }
    const filter = (taskSearchInput.value || '').toLowerCase();
    const lists = currentJsonData?.lijsten || [];

    if (lists.length === 0) {
      listsCardsContainer.innerHTML = '<div class="log-entry">Geen takenlijsten gevonden.</div>';
      return;
    }

    let html = '';
    lists.forEach(l => {
      const filteredTasks = (l.taken || []).filter(t => 
        !filter || t.title.toLowerCase().includes(filter) || l.titel.toLowerCase().includes(filter)
      );

      if (filter && filteredTasks.length === 0) return;

      html += `
        <div class="list-card">
          <div class="list-card-header">
            <span class="list-card-title">${l.titel}</span>
            <span class="tag">${filteredTasks.length} taken</span>
          </div>
          <div class="list-card-body">
            ${filteredTasks.map(t => `
              <div class="task-item">
                <input type="checkbox" ${t.status === 'completed' ? 'checked' : ''} disabled>
                <div class="task-details">
                  <div class="task-title ${t.status === 'completed' ? 'completed' : ''}">${t.title}</div>
                  ${t.notes ? `<div class="task-notes">${t.notes}</div>` : ''}
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    });

    listsCardsContainer.innerHTML = html || '<div class="log-entry">Geen taken gevonden die voldoen aan het zoekfilter.</div>';
  }

  taskSearchInput.addEventListener('input', renderTasksView);

  // --- Accounts Management ---
  async function loadAccounts() {
    try {
      const res = await fetch(`${rootPath}/api/accounts`);
      const data = await res.json();
      allAccounts = data.accounts || [];

      if (allAccounts.length === 0) {
        accountsListContainer.innerHTML = '<div class="log-entry">Nog geen Google accounts gekoppeld. Klik op "+ Account Toevoegen".</div>';
      } else {
        accountsListContainer.innerHTML = allAccounts.map(acc => `
          <div class="account-card">
            <div class="account-card-header">
              <span class="account-name">${acc.name}</span>
              <button class="btn btn-sm btn-ghost" style="color: var(--danger);" onclick="window.deleteAccount('${acc.id}')">Verwijderen</button>
            </div>
            <div class="account-email">${acc.email}</div>
            <div class="tag" style="align-self: flex-start; background: rgba(35, 134, 54, 0.2); color: #3fb950;">Gekoppeld & Actief</div>
          </div>
        `).join('');
      }

      // Check OAuth config status
      const cfgRes = await fetch(`${rootPath}/api/oauth/config`);
      const cfg = await cfgRes.json();
      oauthStatusBox.innerHTML = cfg.has_client_secret 
        ? `<span style="color: #3fb950;">✓ client_secret.json is aanwezig en geconfigureerd (Client ID: ${cfg.client_id || 'Actief'}).</span>`
        : `<span style="color: #f85149;">✗ Geen client_secret.json gevonden in /data.</span>`;
    } catch (e) {
      console.error(e);
    }
  }

  window.deleteAccount = async function(accId) {
    if (!confirm('Weet je zeker dat je dit account wilt ontkoppelen?')) return;
    try {
      await fetch(`${rootPath}/api/accounts/${accId}`, { method: 'DELETE' });
      showToast('Account ontkoppeld.');
      loadAccounts();
      loadStatus();
    } catch (e) {
      showToast('Fout bij ontkoppelen account', true);
    }
  };

  // Modal Controls
  btnOpenAddAccount.addEventListener('click', () => {
    modalAddAccount.classList.add('active');
  });

  const closeModal = () => modalAddAccount.classList.remove('active');
  btnCloseModal.addEventListener('click', closeModal);
  btnCancelAddAccount.addEventListener('click', closeModal);

  btnSaveAccount.addEventListener('click', async () => {
    const name = document.getElementById('acc-form-name').value.trim();
    const email = document.getElementById('acc-form-email').value.trim();
    const token = document.getElementById('acc-form-token').value.trim();

    if (!name || !email || !token) {
      alert('Vul alle velden in.');
      return;
    }

    btnSaveAccount.disabled = true;
    try {
      const res = await fetch(`${rootPath}/api/accounts/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          email: email,
          refresh_token: token
        })
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Account "${name}" succesvol gekoppeld! 🎉`);
        closeModal();
        loadAccounts();
        loadStatus();
      } else {
        alert('Fout: ' + (data.detail || 'Kon account niet toevoegen'));
      }
    } catch (e) {
      alert('Fout bij toevoegen: ' + e.message);
    } finally {
      btnSaveAccount.disabled = false;
    }
  });

  // Initial loads
  loadStatus();
  loadJsonExport();
  setInterval(loadStatus, 10000); // Polling status
});
