document.addEventListener('DOMContentLoaded', () => {
  const rootPath = document.body.dataset.rootPath || '';
  
  // Tab Switcher between JSON Editor, Taken Beheerder and Kapitein Verdeler
  const tabBtnEditor = document.getElementById('tab-btn-editor');
  const tabBtnManager = document.getElementById('tab-btn-manager');
  const tabBtnDivider = document.getElementById('tab-btn-divider');
  
  const viewEditor = document.getElementById('view-editor');
  const viewManager = document.getElementById('view-manager');
  const viewDivider = document.getElementById('view-divider');

  function switchTab(activeBtn, activeView) {
    [tabBtnEditor, tabBtnManager, tabBtnDivider].forEach(b => b.classList.remove('active'));
    [viewEditor, viewManager, viewDivider].forEach(v => v.style.display = 'none');
    activeBtn.classList.add('active');
    activeView.style.display = 'flex';
  }

  tabBtnEditor.addEventListener('click', () => switchTab(tabBtnEditor, viewEditor));
  
  tabBtnManager.addEventListener('click', () => {
    switchTab(tabBtnManager, viewManager);
    loadManagerTasks();
  });

  tabBtnDivider.addEventListener('click', () => {
    switchTab(tabBtnDivider, viewDivider);
    initDividerWizard();
  });

  // Toast Helper
  const toast = document.getElementById('toast');
  function showToast(message, isError = false) {
    toast.textContent = message;
    toast.style.background = isError ? '#da3633' : '#1f6feb';
    toast.classList.add('show');
    setTimeout(() => { toast.classList.remove('show'); }, 3000);
  }

  // =========================================================================
  // STATE VARIABLES
  // =========================================================================
  let wizardInitialized = false;
  let allCaptainTasks = [];
  let royPoints = {};
  let karenPoints = {};
  let averageScores = []; // [{ task, royPts, karenPts, avgPts }]

  // Draft State
  let availablePool = [];
  let royChosenTasks = [];
  let karenChosenTasks = [];
  let royTotalScore = 0;
  let karenTotalScore = 0;
  let currentTurn = 'roy'; // 'roy' of 'karen'

  // =========================================================================
  // 0. TAKEN BEHEERDER & CATEGORIE VERSCHUIVER LOGIC (MET SUB-LIJSTEN)
  // =========================================================================
  let managerTasks = [];
  let pendingReassignments = {}; // { taskId: { task_id, current_list_id, target_list_title, title, notes, status } }

  const managerTbody = document.getElementById('manager-tasks-tbody');
  const managerStatsTag = document.getElementById('manager-stats-tag');
  const managerSearch = document.getElementById('manager-search');
  const managerFilterList = document.getElementById('manager-filter-list');
  const managerFilterSublist = document.getElementById('manager-filter-sublist');
  const btnReloadManager = document.getElementById('btn-reload-manager');
  const btnSaveReassignments = document.getElementById('btn-save-reassignments');
  const pendingCountSpan = document.getElementById('reassign-pending-count');

  const available5Lists = [
    '01. Roy Persoonlijk',
    '02. Karen Persoonlijk',
    '03. Kapitein Roy',
    '04. Kapitein Karen',
    '05. Wisselende Kapiteins'
  ];

  function extractSublist(notes, listTitle, taskTitle) {
    if (notes) {
      const match = notes.match(/^\[(.*?)\]/);
      if (match) return match[1];
    }
    const tLow = ((taskTitle || '') + ' ' + (notes || '')).toLowerCase();
    
    if (listTitle.includes('Roy Persoonlijk')) {
      if (tLow.includes('brevet') || tLow.includes('zeilboot') || tLow.includes('buitenboordmotor') || tLow.includes('speervissen') || tLow.includes('portugal')) {
        return "Hobby's & Vrije Tijd";
      }
      return "Persoonlijke Zorg";
    }
    if (listTitle.includes('Karen Persoonlijk')) return "Persoonlijke Zorg";
    if (listTitle.includes('Kapitein Roy')) {
      if (tLow.includes('gezinshuis') || tLow.includes('triade') || tLow.includes('bereikbaarheid') || tLow.includes('evaluatie') || tLow.includes('rapportage')) {
        return "Gezinshuis";
      }
      return "Techniek & Beheer";
    }
    if (listTitle.includes('Kapitein Karen')) {
      if (tLow.includes('anticonceptie')) return "Persoonlijke Zorg";
      if (tLow.includes('kavelweg')) return "Gezinshuis";
      return "Huishouden & Zorg";
    }
    if (listTitle.includes('Wisselende Kapiteins')) {
      if (tLow.includes('verwarming kelder')) return "Bouw - Verwarming Kelder";
      if (tLow.includes('studio dave')) return "Bouw - Studio Dave";
      if (tLow.includes('studio rahiena')) return "Bouw - Studio Rahiena";
      if (tLow.includes('eigen studio')) return "Bouw - Eigen Studio";
      if (tLow.includes('thuisaccu')) return "Bouw - Thuisaccu";
      if (tLow.includes('home assistant')) return "Bouw - Home Assistant";
      const bouwKw = ['waterzijde', 'luchtleidingen', 'ha regeling', 'elektra', 'gipsplaten', 'xps', 'laminaat', 'keuken', 'naden', 'rachelwerk', 'luchtkanalen', 'muren', 'voorzetwanden', 'leidingen', 'meterkast', '3d-ontwerp', 'packs', 'omvormer', 'pv-panelen', 'ac/dc', 'mqtt', 'esp ', 'dashboard'];
      if (bouwKw.some(k => tLow.includes(k))) return "Bouw Woning";
      if (tLow.includes('maandrapportage') || tLow.includes('evaluatie') || tLow.includes('triade') || tLow.includes('bereikbaarheid') || tLow.includes('gastheerschap') || tLow.includes('beschikbaarheid')) return "Gezinshuis";
      return "Wisselend & Gezin";
    }
    return "Algemeen";
  }

  async function loadManagerTasks() {
    managerTbody.innerHTML = '<tr><td colspan="3" class="loading-cell">Taken ophalen uit alle 5 Google Tasks lijsten...</td></tr>';
    pendingReassignments = {};
    updatePendingBadge();

    try {
      const res = await fetch(`${rootPath}/api/tasks/all`);
      if (!res.ok) throw new Error('Kon taken niet ophalen');
      const data = await res.json();
      const rawTasks = data.tasks || [];
      // Filter out folder header tasks so only real tasks appear in the list
      managerTasks = rawTasks.filter(t => !t.title.startsWith('📂 '));
      managerStatsTag.textContent = `${managerTasks.length} taken in 5 lijsten`;
      
      // Update sublist filter options
      const allSublists = new Set();
      managerTasks.forEach(t => {
        allSublists.add(extractSublist(t.notes, t.current_list_title, t.title));
      });
      
      managerFilterSublist.innerHTML = '<option value="all">Alle Sub-lijsten</option>' + 
        Array.from(allSublists).sort().map(s => `<option value="${s}">📂 ${s}</option>`).join('');

      renderManagerTable();
    } catch (e) {
      managerTbody.innerHTML = `<tr><td colspan="3" class="status-msg error">Fout: ${e.message}</td></tr>`;
    }
  }

  function renderManagerTable() {
    const query = (managerSearch.value || '').toLowerCase().trim();
    const listFilter = managerFilterList.value;
    const subFilter = managerFilterSublist.value;

    const filtered = managerTasks.filter(t => {
      const sub = extractSublist(t.notes, t.current_list_title, t.title);
      const matchesSearch = t.title.toLowerCase().includes(query) || (t.notes || '').toLowerCase().includes(query) || sub.toLowerCase().includes(query);
      const matchesList = (listFilter === 'all') || (t.current_list_title === listFilter);
      const matchesSub = (subFilter === 'all') || (sub === subFilter);
      return matchesSearch && matchesList && matchesSub;
    });

    if (filtered.length === 0) {
      managerTbody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:20px; color:var(--text-muted);">Geen taken gevonden met dit filter.</td></tr>';
      return;
    }

    // Group by Sub-list
    const grouped = {};
    filtered.forEach(t => {
      const sub = extractSublist(t.notes, t.current_list_title, t.title);
      if (!grouped[sub]) grouped[sub] = [];
      grouped[sub].push(t);
    });

    let html = '';
    Object.keys(grouped).sort().forEach(subName => {
      const count = grouped[subName].length;
      html += `
        <tr class="sublist-header-row">
          <td colspan="3">
            <div class="sublist-header-badge">
              <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
              <strong>Sub-lijst: ${subName}</strong>
              <span class="tag" style="margin-left:auto;">${count} taken</span>
            </div>
          </td>
        </tr>
      `;

      grouped[subName].forEach(t => {
        const isChanged = !!pendingReassignments[t.id];
        const selectedTarget = isChanged ? pendingReassignments[t.id].target_list_title : t.current_list_title;

        const optionsHtml = available5Lists.map(l => 
          `<option value="${l}" ${l === selectedTarget ? 'selected' : ''}>${l}</option>`
        ).join('');

        // Clean display notes
        const cleanNotes = (t.notes || '').replace(/^\[(.*?)\]\s*/, '');

        html += `
          <tr class="${isChanged ? 'modified' : ''}" data-id="${t.id}">
            <td style="padding-left:24px;">
              <strong>${t.title}</strong>
              ${cleanNotes ? `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${cleanNotes}</div>` : ''}
            </td>
            <td>
              <span class="tag" style="font-size:11px;">${t.current_list_title}</span>
            </td>
            <td>
              <select class="task-list-select ${isChanged ? 'changed' : ''}" data-id="${t.id}">
                ${optionsHtml}
              </select>
            </td>
          </tr>
        `;
      });
    });

    managerTbody.innerHTML = html;

    // Attach change handlers
    managerTbody.querySelectorAll('.task-list-select').forEach(sel => {
      sel.addEventListener('change', () => {
        const taskId = sel.dataset.id;
        const targetList = sel.value;
        const task = managerTasks.find(t => t.id === taskId);
        if (!task) return;

        if (targetList !== task.current_list_title) {
          pendingReassignments[taskId] = {
            task_id: task.id,
            current_list_id: task.current_list_id,
            target_list_title: targetList,
            title: task.title,
            notes: task.notes,
            status: task.status
          };
          sel.classList.add('changed');
          sel.closest('tr').classList.add('modified');
        } else {
          delete pendingReassignments[taskId];
          sel.classList.remove('changed');
          sel.closest('tr').classList.remove('modified');
        }
        updatePendingBadge();
      });
    });
  }

  function updatePendingBadge() {
    const count = Object.keys(pendingReassignments).length;
    pendingCountSpan.textContent = count;
    btnSaveReassignments.disabled = (count === 0);
  }

  managerSearch.addEventListener('input', renderManagerTable);
  managerFilterList.addEventListener('change', renderManagerTable);
  managerFilterSublist.addEventListener('change', renderManagerTable);
  btnReloadManager.addEventListener('click', loadManagerTasks);

  btnSaveReassignments.addEventListener('click', async () => {
    const moves = Object.values(pendingReassignments);
    if (moves.length === 0) return;

    btnSaveReassignments.disabled = true;
    btnSaveReassignments.innerHTML = '<span class="badge syncing">Bezig met verplaatsen...</span>';
    showToast(`Bezig met het verplaatsen van ${moves.length} taken naar Google Tasks...`);

    try {
      const res = await fetch(`${rootPath}/api/tasks/reassign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ moves })
      });
      const data = await res.json();
      if (data.success) {
        showToast(`✓ ${data.moved_count} taken succesvol verplaatst in Google Tasks! 🎉`);
        loadManagerTasks();
        loadJsonExport();
      } else {
        throw new Error(data.error || 'Fout');
      }
    } catch (e) {
      showToast('Fout bij verplaatsen: ' + e.message, true);
    } finally {
      btnSaveReassignments.disabled = false;
      btnSaveReassignments.innerHTML = `
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
        Wijzigingen Syncen naar Google Tasks! (<span id="reassign-pending-count">0</span>)
      `;
      updatePendingBadge();
    }
  });

  // =========================================================================
  // 1. JSON EDITOR & DEBUG LOG LOGIC
  // =========================================================================
  const btnSyncNow = document.getElementById('btn-sync-now');
  const syncBadge = document.getElementById('sync-status-badge');
  const jsonTextarea = document.getElementById('json-textarea');
  const jsonStatusMsg = document.getElementById('json-status-msg');
  const jsonStatsTag = document.getElementById('json-stats-tag');
  
  const btnCopyJson = document.getElementById('btn-copy-json');
  const btnFormatJson = document.getElementById('btn-format-json');
  const btnPasteJson = document.getElementById('btn-paste-json');
  const btnReloadJson = document.getElementById('btn-reload-json');
  const btnApplyJson = document.getElementById('btn-save-json') || document.getElementById('btn-apply-json');

  const logsContainer = document.getElementById('debug-log-view');
  const debugLastSync = document.getElementById('debug-last-sync');
  const btnClearLogs = document.getElementById('btn-clear-logs');
  const btnRefreshLogs = document.getElementById('btn-refresh-logs');

  function appendClientLog(msg, level = 'info') {
    if (!logsContainer) return;
    const time = new Date().toTimeString().split(' ')[0];
    const el = document.createElement('div');
    el.className = `log-entry level-${level}`;
    el.textContent = `[${time}] [CLIENT-${level.toUpperCase()}] ${msg}`;
    logsContainer.prepend(el);
  }

  async function loadLogsAndStatus() {
    try {
      const res = await fetch(`${rootPath}/api/status`);
      if (!res.ok) return;
      const data = await res.json();
      if (debugLastSync) debugLastSync.textContent = `Laatste sync: ${data.last_sync_time || 'Nog niet'}`;
      if (logsContainer && data.logs && data.logs.length > 0) {
        logsContainer.innerHTML = data.logs.map(l => 
          `<div class="log-entry level-${l.level}">[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}</div>`
        ).join('');
      }
    } catch (e) {}
  }

  if (btnClearLogs) {
    btnClearLogs.addEventListener('click', () => {
      if (logsContainer) logsContainer.innerHTML = '<div class="log-entry">[SYSTEM] Logboek gewist.</div>';
      showToast('Logboek gewist');
    });
  }

  if (btnRefreshLogs) {
    btnRefreshLogs.addEventListener('click', () => {
      loadLogsAndStatus();
      showToast('Logs ververst');
    });
  }

  jsonTextarea.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const start = jsonTextarea.selectionStart;
      const end = jsonTextarea.selectionEnd;
      jsonTextarea.value = jsonTextarea.value.substring(0, start) + '  ' + jsonTextarea.value.substring(end);
      jsonTextarea.selectionStart = jsonTextarea.selectionEnd = start + 2;
    }
  });

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

  async function loadJsonExport() {
    jsonStatusMsg.textContent = 'JSON ophalen vanuit Google Tasks...';
    jsonStatusMsg.className = 'status-msg';
    syncBadge.textContent = 'Laden...';
    
    try {
      const res = await fetch(`${rootPath}/api/json/export`);
      if (!res.ok) throw new Error('Kon JSON niet ophalen');
      const currentJsonData = await res.json();
      
      jsonTextarea.value = JSON.stringify(currentJsonData, null, 2);
      jsonTextarea.scrollTop = 0;

      const totalLists = currentJsonData.totaal_lijsten || 0;
      const totalTasks = currentJsonData.totaal_taken || 0;
      jsonStatsTag.textContent = `${totalTasks} taken in ${totalLists} lijsten`;
      jsonStatusMsg.textContent = `✓ Geladen: ${totalTasks} taken in ${totalLists} lijsten.`;
      jsonStatusMsg.className = 'status-msg success';
      syncBadge.textContent = 'Klaar';
      loadLogsAndStatus();
    } catch (e) {
      jsonStatusMsg.textContent = '✗ Fout bij ophalen JSON: ' + e.message;
      jsonStatusMsg.className = 'status-msg error';
      syncBadge.textContent = 'Fout';
    }
  }

  if (btnCopyJson) {
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
  }

  if (btnFormatJson) {
    btnFormatJson.addEventListener('click', () => {
      try {
        const parsed = JSON.parse(jsonTextarea.value);
        jsonTextarea.value = JSON.stringify(parsed, null, 2);
        jsonStatusMsg.textContent = '✓ JSON geformatteerd en gevalideerd!';
        jsonStatusMsg.className = 'status-msg success';
        showToast('JSON netjes geformatteerd! ✨');
      } catch (e) {
        jsonStatusMsg.textContent = '⚠ Syntaxfout: ' + e.message;
        jsonStatusMsg.className = 'status-msg error';
        showToast('Ongeldige JSON syntax', true);
      }
    });
  }

  if (btnPasteJson) {
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
        jsonTextarea.focus();
        showToast('Plak direct met Ctrl+V / Cmd+V in het tekstveld');
      }
    });
  }

  if (btnReloadJson) {
    btnReloadJson.addEventListener('click', () => {
      loadJsonExport();
      showToast('JSON herladen vanuit Google');
    });
  }

  async function applyJsonToGoogle() {
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
        appendClientLog('Google Tasks synchronisatie succesvol voltooid!', 'success');
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
    } finally {
      btnApplyJson.disabled = false;
      btnSyncNow.disabled = false;
    }
  }

  if (btnApplyJson) btnApplyJson.addEventListener('click', applyJsonToGoogle);
  if (btnSyncNow) btnSyncNow.addEventListener('click', applyJsonToGoogle);

  // Initial loads
  loadManagerTasks();
  loadJsonExport();
  loadLogsAndStatus();
  setInterval(loadLogsAndStatus, 10000);

  // =========================================================================
  // 2. KAPITEIN VERDELER WIZARD LOGIC (STAPPEN 1 T/M 5)
  // =========================================================================

  function setWizardStep(stepNum) {
    for (let i = 1; i <= 5; i++) {
      const stepEl = document.getElementById(`step-${i}-content`);
      if (stepEl) stepEl.style.display = (i === stepNum) ? 'flex' : 'none';
      
      const stepItem = document.querySelector(`.step-item[data-step="${i}"]`);
      if (stepItem) {
        stepItem.classList.remove('active', 'completed');
        if (i === stepNum) stepItem.classList.add('active');
        else if (i < stepNum) stepItem.classList.add('completed');
      }
    }
  }

  async function initDividerWizard() {
    setWizardStep(1);

    const grid = document.getElementById('step-1-points-grid');
    grid.innerHTML = '<div class="loading-spinner">Kapiteinstaken ophalen uit 03. Kapitein Roy & 04. Kapitein Karen...</div>';

    try {
      const res = await fetch(`${rootPath}/api/divider/tasks`);
      if (!res.ok) throw new Error('Kon kapiteinstaken niet ophalen');
      const data = await res.json();
      allCaptainTasks = data.tasks || [];
      
      if (!allCaptainTasks.length) {
        grid.innerHTML = '<div class="status-msg">Geen taken gevonden in Kapitein Roy & Kapitein Karen.</div>';
        return;
      }

      const totalBudget = allCaptainTasks.length * 10;
      document.querySelectorAll('.stepper-total-pts').forEach(el => el.textContent = totalBudget);
      const royLabel = document.getElementById('roy-total-budget-label');
      if (royLabel) royLabel.textContent = `${totalBudget} punten (${allCaptainTasks.length} taken × 10)`;
      const karenLabel = document.getElementById('karen-total-budget-label');
      if (karenLabel) karenLabel.textContent = `${totalBudget} punten (${allCaptainTasks.length} taken × 10)`;

      initPointsStep(1, 'roy');
    } catch (e) {
      grid.innerHTML = `<div class="status-msg error">Fout: ${e.message}</div>`;
    }
  }

  // --- STAP 1 & 2: Points Allocation (10pt per taak standaard, totaal = N * 10) ---
  function initPointsStep(stepNum, player) {
    const grid = document.getElementById(`step-${stepNum}-points-grid`);
    const totalBudget = (allCaptainTasks.length || 1) * 10;
    const pointsObj = (player === 'roy') ? royPoints : karenPoints;

    // Set default points to 10 for every task
    allCaptainTasks.forEach((t) => {
      if (pointsObj[t.title] === undefined) {
        pointsObj[t.title] = 10;
      }
    });

    function renderPointsGrid() {
      grid.innerHTML = allCaptainTasks.map((t) => `
        <div class="point-task-row">
          <div class="point-task-info">
            <div class="point-task-title">${t.title}</div>
            <div class="point-task-notes">
              <span class="tag" style="font-size:10px; padding:1px 5px;">${t.current_list_title}</span>
              ${t.notes ? '• ' + t.notes : ''}
            </div>
          </div>
          <div class="point-controls">
            <button class="btn btn-sm btn-outline btn-pt-change" data-delta="-20" data-title="${t.title}" title="-20 punten">-20</button>
            <button class="btn btn-sm btn-outline btn-pt-change" data-delta="-5" data-title="${t.title}" title="-5 punten">-5</button>
            <button class="btn btn-sm btn-outline btn-pt-change" data-delta="-1" data-title="${t.title}" title="-1 punt">-1</button>
            <input type="number" class="point-input" data-title="${t.title}" value="${pointsObj[t.title] !== undefined ? pointsObj[t.title] : 10}" min="0" max="1000">
            <button class="btn btn-sm btn-outline btn-pt-change" data-delta="1" data-title="${t.title}" title="+1 punt">+1</button>
            <button class="btn btn-sm btn-outline btn-pt-change" data-delta="5" data-title="${t.title}" title="+5 punten">+5</button>
            <button class="btn btn-sm btn-outline btn-pt-change" data-delta="20" data-title="${t.title}" title="+20 punten">+20</button>
          </div>
        </div>
      `).join('');

      // Input changes
      grid.querySelectorAll('.point-input').forEach(inp => {
        inp.addEventListener('input', () => {
          const val = parseInt(inp.value) || 0;
          pointsObj[inp.dataset.title] = Math.max(0, val);
          updateBudgetStatus(stepNum, player);
        });
      });

      // Point delta buttons (+1, -1, +5, -5, +20, -20)
      grid.querySelectorAll('.btn-pt-change').forEach(btn => {
        btn.addEventListener('click', () => {
          const t = btn.dataset.title;
          const delta = parseInt(btn.dataset.delta) || 0;
          pointsObj[t] = Math.max(0, (pointsObj[t] || 0) + delta);
          renderPointsGrid();
        });
      });

      updateBudgetStatus(stepNum, player);
    }

    renderPointsGrid();
  }

  function updateBudgetStatus(stepNum, player) {
    const totalBudget = (allCaptainTasks.length || 1) * 10;
    const pointsObj = (player === 'roy') ? royPoints : karenPoints;
    const totalAssigned = Object.values(pointsObj).reduce((sum, v) => sum + (parseInt(v) || 0), 0);
    const remaining = totalBudget - totalAssigned;

    const textEl = document.getElementById(`${player}-budget-text`);
    const fillEl = document.getElementById(`${player}-budget-progress`);

    if (textEl && fillEl) {
      textEl.textContent = `${totalAssigned} / ${totalBudget} punten verdeeld (${remaining >= 0 ? remaining + ' over' : Math.abs(remaining) + ' te veel!'})`;
      
      const pct = Math.min(100, Math.max(0, (totalAssigned / totalBudget) * 100));
      fillEl.style.width = `${pct}%`;

      fillEl.className = 'progress-bar-fill';
      if (totalAssigned > totalBudget) fillEl.classList.add('danger');
      else if (totalAssigned === totalBudget) fillEl.style.background = '#3fb950';
    }
  }

  // Navigation handlers
  const btnStep1Next = document.getElementById('btn-step-1-next');
  if (btnStep1Next) {
    btnStep1Next.addEventListener('click', () => {
      setWizardStep(2);
      initPointsStep(2, 'karen');
    });
  }

  const btnStep2Prev = document.getElementById('btn-step-2-prev');
  if (btnStep2Prev) {
    btnStep2Prev.addEventListener('click', () => setWizardStep(1));
  }

  const btnStep2Next = document.getElementById('btn-step-2-next');
  if (btnStep2Next) {
    btnStep2Next.addEventListener('click', () => {
      calculateAverages();
      setWizardStep(3);
    });
  }

  // --- STAP 3: Calculate & Render Averages ---
  function calculateAverages() {
    averageScores = allCaptainTasks.map(t => {
      const r = parseInt(royPoints[t.title]) || 0;
      const k = parseInt(karenPoints[t.title]) || 0;
      const avg = Math.round(((r + k) / 2) * 10) / 10;
      return {
        task: t,
        title: t.title,
        notes: t.notes,
        current_list_title: t.current_list_title,
        royPts: r,
        karenPts: k,
        avgPts: avg
      };
    });

    // Sort descending by average points (zwaarste taken bovenaan)
    averageScores.sort((a, b) => b.avgPts - a.avgPts);

    const tbody = document.getElementById('step-3-averages-tbody');
    if (tbody) {
      tbody.innerHTML = averageScores.map(item => `
        <tr>
          <td><strong>${item.title}</strong><br><small style="color:var(--text-muted)"><span class="tag" style="font-size:10px; padding:1px 5px;">${item.current_list_title}</span> ${item.notes || ''}</small></td>
          <td style="color:var(--roy-color); font-weight:700;">${item.royPts} pt</td>
          <td style="color:var(--karen-color); font-weight:700;">${item.karenPts} pt</td>
          <td><span class="tag" style="font-size:12px; font-weight:700;">⭐ ${item.avgPts} pt</span></td>
        </tr>
      `).join('');
    }
  }

  const btnStep3Prev = document.getElementById('btn-step-3-prev');
  if (btnStep3Prev) {
    btnStep3Prev.addEventListener('click', () => setWizardStep(2));
  }

  const btnStep3Next = document.getElementById('btn-step-3-next');
  if (btnStep3Next) {
    btnStep3Next.addEventListener('click', () => {
      setWizardStep(4);
      initStep4Draft();
    });
  }

  // --- STAP 4: Draft / Keuzerondes ---
  function initStep4Draft() {
    const choiceBox = document.getElementById('starter-choice-box');
    const arena = document.getElementById('draft-arena');
    if (choiceBox) choiceBox.style.display = 'flex';
    if (arena) arena.style.display = 'none';

    availablePool = [...averageScores];
    royChosenTasks = [];
    karenChosenTasks = [];
    royTotalScore = 0;
    karenTotalScore = 0;
  }

  function startDraft(starter) {
    currentTurn = starter;
    const choiceBox = document.getElementById('starter-choice-box');
    const arena = document.getElementById('draft-arena');
    if (choiceBox) choiceBox.style.display = 'none';
    if (arena) arena.style.display = 'block';
    renderDraftArena();
  }

  const btnStartRoy = document.getElementById('btn-start-roy');
  const btnStartKaren = document.getElementById('btn-start-karen');
  if (btnStartRoy) btnStartRoy.addEventListener('click', () => startDraft('roy'));
  if (btnStartKaren) btnStartKaren.addEventListener('click', () => startDraft('karen'));

  function pickTask(item) {
    if (currentTurn === 'roy') {
      royChosenTasks.push(item);
      royTotalScore += item.avgPts;
    } else {
      karenChosenTasks.push(item);
      karenTotalScore += item.avgPts;
    }

    // Remove from available pool
    availablePool = availablePool.filter(i => i.title !== item.title);

    // Beurtwissel logica volgens regels:
    if (royTotalScore < karenTotalScore) {
      currentTurn = 'roy';
    } else if (karenTotalScore < royTotalScore) {
      currentTurn = 'karen';
    } else {
      currentTurn = (currentTurn === 'roy') ? 'karen' : 'roy';
    }

    renderDraftArena();
  }

  function renderDraftArena() {
    const isKaren = (currentTurn === 'karen');
    const banner = document.getElementById('turn-banner');
    if (banner) banner.className = `turn-banner ${isKaren ? 'karen-turn' : ''}`;
    
    const turnText = document.getElementById('turn-text');
    if (turnText) turnText.textContent = isKaren ? 'Karen mag kiezen' : 'Roy mag kiezen';

    const turnSubtext = document.getElementById('turn-subtext');
    if (turnSubtext) {
      turnSubtext.textContent = isKaren 
        ? `Karen heeft ${karenTotalScore.toFixed(1)} pt vs Roy ${royTotalScore.toFixed(1)} pt.`
        : `Roy heeft ${royTotalScore.toFixed(1)} pt vs Karen ${karenTotalScore.toFixed(1)} pt.`;
    }

    // Scores & Balance
    const royCurrentPts = document.getElementById('roy-current-pts');
    if (royCurrentPts) royCurrentPts.textContent = `${royTotalScore.toFixed(1)} pt`;
    
    const royTasksCount = document.getElementById('roy-tasks-count');
    if (royTasksCount) royTasksCount.textContent = `${royChosenTasks.length} taken`;

    const karenCurrentPts = document.getElementById('karen-current-pts');
    if (karenCurrentPts) karenCurrentPts.textContent = `${karenTotalScore.toFixed(1)} pt`;

    const karenTasksCount = document.getElementById('karen-tasks-count');
    if (karenTasksCount) karenTasksCount.textContent = `${karenChosenTasks.length} taken`;

    const totalAssigned = (royTotalScore + karenTotalScore) || 1;
    const royPct = Math.round((royTotalScore / totalAssigned) * 100);
    const karenPct = 100 - royPct;

    const balanceFillRoy = document.getElementById('balance-fill-roy');
    if (balanceFillRoy) balanceFillRoy.style.width = `${royPct}%`;

    const balanceFillKaren = document.getElementById('balance-fill-karen');
    if (balanceFillKaren) balanceFillKaren.style.width = `${karenPct}%`;

    // Available Tasks
    const availCount = document.getElementById('available-tasks-count');
    if (availCount) availCount.textContent = availablePool.length;

    const availableList = document.getElementById('available-tasks-list');
    const btnFinish = document.getElementById('btn-step-4-finish');
    
    if (availableList) {
      if (availablePool.length === 0) {
        availableList.innerHTML = '<div class="status-msg success">🎉 Alle taken zijn verdeeld!</div>';
        if (btnFinish) btnFinish.style.display = 'inline-flex';
      } else {
        if (btnFinish) btnFinish.style.display = 'none';
        availableList.innerHTML = availablePool.map(item => `
          <div class="draft-pick-item" data-title="${item.title}">
            <div>
              <strong>${item.title}</strong>
              <div style="font-size:11px; color:var(--text-muted)"><span class="tag" style="font-size:9px; padding:1px 4px;">${item.current_list_title}</span> ${item.notes || ''}</div>
            </div>
            <span class="draft-pick-pts">${item.avgPts} pt</span>
          </div>
        `).join('');

        availableList.querySelectorAll('.draft-pick-item').forEach(el => {
          el.addEventListener('click', () => {
            const item = availablePool.find(i => i.title === el.dataset.title);
            if (item) pickTask(item);
          });
        });
      }
    }

    // Chosen Tasks
    const royChosenList = document.getElementById('roy-chosen-list');
    if (royChosenList) {
      royChosenList.innerHTML = royChosenTasks.map(i => `
        <div class="chosen-item">
          <span>${i.title}</span>
          <strong style="color:var(--roy-color)">${i.avgPts} pt</strong>
        </div>
      `).join('');
    }

    const karenChosenList = document.getElementById('karen-chosen-list');
    if (karenChosenList) {
      karenChosenList.innerHTML = karenChosenTasks.map(i => `
        <div class="chosen-item">
          <span>${i.title}</span>
          <strong style="color:var(--karen-color)">${i.avgPts} pt</strong>
        </div>
      `).join('');
    }
  }

  const btnStep4Prev = document.getElementById('btn-step-4-prev');
  if (btnStep4Prev) {
    btnStep4Prev.addEventListener('click', () => setWizardStep(3));
  }

  const btnStep4Finish = document.getElementById('btn-step-4-finish');
  if (btnStep4Finish) {
    btnStep4Finish.addEventListener('click', () => {
      setWizardStep(5);
      renderStep5Finale();
    });
  }

  // --- STAP 5: Finale Summary & Google Tasks Apply ---
  function renderStep5Finale() {
    const royStats = document.getElementById('final-roy-stats');
    if (royStats) royStats.textContent = `${royChosenTasks.length} taken | ${royTotalScore.toFixed(1)} pt`;

    const karenStats = document.getElementById('final-karen-stats');
    if (karenStats) karenStats.textContent = `${karenChosenTasks.length} taken | ${karenTotalScore.toFixed(1)} pt`;

    const royList = document.getElementById('final-roy-list');
    if (royList) {
      royList.innerHTML = royChosenTasks.map(i => `
        <li>
          <span>${i.title}</span>
          <strong style="color:var(--roy-color)">${i.avgPts} pt</strong>
        </li>
      `).join('');
    }

    const karenList = document.getElementById('final-karen-list');
    if (karenList) {
      karenList.innerHTML = karenChosenTasks.map(i => `
        <li>
          <span>${i.title}</span>
          <strong style="color:var(--karen-color)">${i.avgPts} pt</strong>
        </li>
      `).join('');
    }
  }

  const btnStep5Prev = document.getElementById('btn-step-5-prev-final');
  if (btnStep5Prev) {
    btnStep5Prev.addEventListener('click', () => setWizardStep(4));
  }

  const btnApplyDivision = document.getElementById('btn-apply-division-google');
  if (btnApplyDivision) {
    btnApplyDivision.addEventListener('click', async () => {
      btnApplyDivision.disabled = true;
      btnApplyDivision.textContent = 'Bezig met synchroniseren naar Google Tasks...';
      showToast('Bezig met toepassen op Google Tasks...');

      try {
        const royPayload = royChosenTasks.map(i => ({
          title: i.title,
          notes: i.notes,
          points: i.avgPts
        }));
        const karenPayload = karenChosenTasks.map(i => ({
          title: i.title,
          notes: i.notes,
          points: i.avgPts
        }));

        const res = await fetch(`${rootPath}/api/divider/apply`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            roy_tasks: royPayload,
            karen_tasks: karenPayload
          })
        });

        const data = await res.json();
        if (data.success) {
          showToast('Kapiteinstaken succesvol verdeeld en gesynchroniseerd met Google Tasks! 🎉');
          btnApplyDivision.textContent = '✓ Gesynchroniseerd met Google Tasks!';
          btnApplyDivision.style.background = '#238636';
          loadJsonExport();
        } else {
          throw new Error(data.error || 'Onbekende fout');
        }
      } catch (e) {
        showToast('Fout bij synchroniseren: ' + e.message, true);
        btnApplyDivision.disabled = false;
        btnApplyDivision.textContent = 'Toepassen & Syncen naar Google Tasks! 🚀';
      }
    });
  }

  // =========================================================================
  // 3. SCHEMATISCH AFDRUKKEN OVERZICHT (PRINT MODAL & SCHEMATIC VIEW)
  // =========================================================================
  const btnOpenPrintModal = document.getElementById('btn-open-print-modal');
  const printModal = document.getElementById('print-modal');
  const btnClosePrintModal = document.getElementById('btn-close-print-modal');
  const btnCancelPrint = document.getElementById('btn-cancel-print');
  const btnExecutePrint = document.getElementById('btn-execute-print');

  const printListsContainer = document.getElementById('print-lists-checkboxes');
  const printSublistsContainer = document.getElementById('print-sublists-checkboxes');
  const printPreviewBox = document.getElementById('print-preview-box');
  const printableArea = document.getElementById('printable-area');
  const printSelectedCount = document.getElementById('print-selected-count');

  const printOptNotes = document.getElementById('print-opt-notes');
  const printOptCheckboxes = document.getElementById('print-opt-checkboxes');
  const printOptStats = document.getElementById('print-opt-stats');

  const btnPrintSelectAllLists = document.getElementById('btn-print-select-all-lists');
  const btnPrintDeselectAllLists = document.getElementById('btn-print-deselect-all-lists');
  const btnPrintSelectAllSublists = document.getElementById('btn-print-select-all-sublists');
  const btnPrintDeselectAllSublists = document.getElementById('btn-print-deselect-all-sublists');

  let selectedPrintLists = new Set(available5Lists);
  let selectedPrintSublists = new Set();

  function openPrintModal() {
    if (!printModal) return;

    // Collect all available sublists across managerTasks
    const allFoundSublists = new Set();
    managerTasks.forEach(t => {
      allFoundSublists.add(extractSublist(t.notes, t.current_list_title, t.title));
    });

    if (selectedPrintSublists.size === 0) {
      selectedPrintSublists = new Set(allFoundSublists);
    }

    // Populate main lists checkboxes
    printListsContainer.innerHTML = available5Lists.map(l => `
      <label class="checkbox-item">
        <input type="checkbox" class="cb-print-list" value="${l}" ${selectedPrintLists.has(l) ? 'checked' : ''}>
        <span>${l}</span>
      </label>
    `).join('');

    // Populate sublists checkboxes
    const sortedSublists = Array.from(allFoundSublists).sort();
    printSublistsContainer.innerHTML = sortedSublists.map(s => `
      <label class="checkbox-item">
        <input type="checkbox" class="cb-print-sublist" value="${s}" ${selectedPrintSublists.has(s) ? 'checked' : ''}>
        <span>📂 ${s}</span>
      </label>
    `).join('');

    // Attach listeners
    printListsContainer.querySelectorAll('.cb-print-list').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) selectedPrintLists.add(cb.value);
        else selectedPrintLists.delete(cb.value);
        renderSchematicPreview();
      });
    });

    printSublistsContainer.querySelectorAll('.cb-print-sublist').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) selectedPrintSublists.add(cb.value);
        else selectedPrintSublists.delete(cb.value);
        renderSchematicPreview();
      });
    });

    renderSchematicPreview();
    printModal.style.display = 'flex';
  }

  function closePrintModal() {
    if (printModal) printModal.style.display = 'none';
  }

  function generateSchematicHtml() {
    const showNotes = printOptNotes ? printOptNotes.checked : true;
    const showCb = printOptCheckboxes ? printOptCheckboxes.checked : true;
    const showStats = printOptStats ? printOptStats.checked : true;

    // Filter tasks
    const tasksToPrint = managerTasks.filter(t => {
      const sub = extractSublist(t.notes, t.current_list_title, t.title);
      return selectedPrintLists.has(t.current_list_title) && selectedPrintSublists.has(sub);
    });

    if (printSelectedCount) {
      printSelectedCount.textContent = tasksToPrint.length;
    }

    if (tasksToPrint.length === 0) {
      return '<div style="padding:20px; text-align:center; color:#64748b;">Geen taken geselecteerd met de huidige filterinstellingen. Vink minimaal één lijst en sublijst aan.</div>';
    }

    // Group tasks by Main List -> Sublist
    const grouped = {};
    available5Lists.forEach(listTitle => {
      if (selectedPrintLists.has(listTitle)) {
        grouped[listTitle] = {};
      }
    });

    tasksToPrint.forEach(t => {
      const listTitle = t.current_list_title;
      const sub = extractSublist(t.notes, listTitle, t.title);
      if (!grouped[listTitle]) grouped[listTitle] = {};
      if (!grouped[listTitle][sub]) grouped[listTitle][sub] = [];
      grouped[listTitle][sub].push(t);
    });

    const nowStr = new Date().toLocaleString('nl-NL', { dateStyle: 'full', timeStyle: 'short' });

    let html = `
      <div class="schematic-sheet">
        <div class="schematic-header">
          <h1>📋 Google Tasks Schematisch Overzicht</h1>
          <div class="schematic-meta">
            <span><strong>Datum:</strong> ${nowStr}</span>
            <span><strong>Totaal Geselecteerd:</strong> ${tasksToPrint.length} taken</span>
            <span><strong>Lijsten:</strong> ${selectedPrintLists.size} van 5</span>
          </div>
        </div>
        <div class="schematic-grid">
    `;

    Object.keys(grouped).forEach(listTitle => {
      const subgroups = grouped[listTitle];
      const subKeys = Object.keys(subgroups);
      const totalInList = subKeys.reduce((acc, k) => acc + subgroups[k].length, 0);

      if (totalInList === 0) return;

      html += `
        <div class="schematic-list-card">
          <div class="schematic-list-title">
            <h2>📑 ${listTitle}</h2>
            ${showStats ? `<span class="schematic-list-badge">${totalInList} taken</span>` : ''}
          </div>
          <div class="schematic-subgroups">
      `;

      subKeys.sort().forEach(subName => {
        const subTasks = subgroups[subName];
        if (subTasks.length === 0) return;

        html += `
          <div class="schematic-subgroup">
            <div class="schematic-subgroup-title">
              <span>📂 ${subName}</span>
              ${showStats ? `<span style="font-size:11px; font-weight:normal; color:#64748b;">(${subTasks.length})</span>` : ''}
            </div>
            <table class="schematic-tasks-table">
              <tbody>
        `;

        subTasks.forEach(t => {
          const cleanNotes = (t.notes || '').replace(/^\[(.*?)\]\s*/, '');
          html += `
            <tr>
              ${showCb ? '<td class="schematic-cb">⬜</td>' : ''}
              <td>
                <div class="schematic-task-main">${t.title}</div>
                ${(showNotes && cleanNotes) ? `<div class="schematic-task-notes">${cleanNotes}</div>` : ''}
              </td>
            </tr>
          `;
        });

        html += `
              </tbody>
            </table>
          </div>
        `;
      });

      html += `
          </div>
        </div>
      `;
    });

    html += `
        </div>
      </div>
    `;

    return html;
  }

  function renderSchematicPreview() {
    const html = generateSchematicHtml();
    if (printPreviewBox) printPreviewBox.innerHTML = html;
  }

  if (btnOpenPrintModal) btnOpenPrintModal.addEventListener('click', openPrintModal);
  if (btnClosePrintModal) btnClosePrintModal.addEventListener('click', closePrintModal);
  if (btnCancelPrint) btnCancelPrint.addEventListener('click', closePrintModal);

  if (printOptNotes) printOptNotes.addEventListener('change', renderSchematicPreview);
  if (printOptCheckboxes) printOptCheckboxes.addEventListener('change', renderSchematicPreview);
  if (printOptStats) printOptStats.addEventListener('change', renderSchematicPreview);

  if (btnPrintSelectAllLists) {
    btnPrintSelectAllLists.addEventListener('click', () => {
      available5Lists.forEach(l => selectedPrintLists.add(l));
      printListsContainer.querySelectorAll('.cb-print-list').forEach(cb => cb.checked = true);
      renderSchematicPreview();
    });
  }

  if (btnPrintDeselectAllLists) {
    btnPrintDeselectAllLists.addEventListener('click', () => {
      selectedPrintLists.clear();
      printListsContainer.querySelectorAll('.cb-print-list').forEach(cb => cb.checked = false);
      renderSchematicPreview();
    });
  }

  if (btnPrintSelectAllSublists) {
    btnPrintSelectAllSublists.addEventListener('click', () => {
      managerTasks.forEach(t => {
        selectedPrintSublists.add(extractSublist(t.notes, t.current_list_title, t.title));
      });
      printSublistsContainer.querySelectorAll('.cb-print-sublist').forEach(cb => cb.checked = true);
      renderSchematicPreview();
    });
  }

  if (btnPrintDeselectAllSublists) {
    btnPrintDeselectAllSublists.addEventListener('click', () => {
      selectedPrintSublists.clear();
      printSublistsContainer.querySelectorAll('.cb-print-sublist').forEach(cb => cb.checked = false);
      renderSchematicPreview();
    });
  }

  if (btnExecutePrint) {
    btnExecutePrint.addEventListener('click', () => {
      const html = generateSchematicHtml();
      printableArea.innerHTML = html;
      window.print();
    });
  }

});
