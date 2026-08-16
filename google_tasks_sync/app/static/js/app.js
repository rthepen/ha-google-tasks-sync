document.addEventListener('DOMContentLoaded', () => {
  const rootPath = document.body.dataset.rootPath || '';
  
  // Tab Switcher between JSON Editor and Kapitein Verdeler
  const tabBtnEditor = document.getElementById('tab-btn-editor');
  const tabBtnDivider = document.getElementById('tab-btn-divider');
  const viewEditor = document.getElementById('view-editor');
  const viewDivider = document.getElementById('view-divider');

  tabBtnEditor.addEventListener('click', () => {
    tabBtnEditor.classList.add('active');
    tabBtnDivider.classList.remove('active');
    viewEditor.style.display = 'flex';
    viewDivider.style.display = 'none';
  });

  tabBtnDivider.addEventListener('click', () => {
    tabBtnDivider.classList.add('active');
    tabBtnEditor.classList.remove('active');
    viewEditor.style.display = 'none';
    viewDivider.style.display = 'flex';
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
  // 1. JSON EDITOR & DEBUG LOG LOGIC
  // =========================================================================
  const btnSyncNow = document.getElementById('btn-sync-now');
  const syncBadge = document.getElementById('sync-status-badge');
  const jsonTextarea = document.getElementById('json-textarea');
  const jsonStatusMsg = document.getElementById('json-status-msg');
  const jsonStatsTag = document.getElementById('json-stats-tag');
  
  const btnCopyJson = document.getElementById('btn-copy-json');
  const btnPasteJson = document.getElementById('btn-paste-json');
  const btnReloadJson = document.getElementById('btn-reload-json');
  const btnApplyJson = document.getElementById('btn-apply-json');

  const logsContainer = document.getElementById('logs-container');
  const debugLastSync = document.getElementById('debug-last-sync');
  const btnClearLogs = document.getElementById('btn-clear-logs');
  const btnRefreshLogs = document.getElementById('btn-refresh-logs');

  function appendClientLog(msg, level = 'info') {
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
      debugLastSync.textContent = `Laatste sync: ${data.last_sync_time || 'Nog niet'}`;
      if (data.logs && data.logs.length > 0) {
        logsContainer.innerHTML = data.logs.map(l => 
          `<div class="log-entry level-${l.level}">[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}</div>`
        ).join('');
      }
    } catch (e) {}
  }

  btnClearLogs.addEventListener('click', () => {
    logsContainer.innerHTML = '<div class="log-entry">[SYSTEM] Logboek gewist.</div>';
    showToast('Logboek gewist');
  });

  btnRefreshLogs.addEventListener('click', () => {
    loadLogsAndStatus();
    showToast('Logs ververst');
  });

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

  btnReloadJson.addEventListener('click', () => {
    loadJsonExport();
    showToast('JSON herladen vanuit Google');
  });

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

  btnApplyJson.addEventListener('click', applyJsonToGoogle);
  btnSyncNow.addEventListener('click', applyJsonToGoogle);

  // Initial loads
  loadJsonExport();
  loadLogsAndStatus();
  setInterval(loadLogsAndStatus, 10000);

  // =========================================================================
  // 2. KAPITEIN VERDELER WIZARD LOGIC (STAPPEN 1 T/M 6)
  // =========================================================================
  let wizardInitialized = false;
  let allCaptainTasks = [];
  let selectedTasks = [];
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

  function setWizardStep(stepNum) {
    for (let i = 1; i <= 6; i++) {
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
    if (wizardInitialized) return;
    wizardInitialized = true;
    setWizardStep(1);

    const container = document.getElementById('step-1-tasks-list');
    container.innerHTML = '<div class="loading-spinner">Kapiteinstaken ophalen uit Google Tasks...</div>';

    try {
      const res = await fetch(`${rootPath}/api/divider/tasks`);
      if (!res.ok) throw new Error('Kon kapiteinstaken niet ophalen');
      const data = await res.json();
      allCaptainTasks = data.tasks || [];
      setupStep1Filters();
      renderStep1Tasks();
    } catch (e) {
      container.innerHTML = `<div class="status-msg error">Fout: ${e.message}</div>`;
    }
  }

  // --- STAP 1: Select Tasks with List Filter Tabs ---
  let currentListFilter = 'all';

  function setupStep1Filters() {
    const filtersContainer = document.getElementById('step-1-filters');
    if (!filtersContainer) return;

    // Update count badges
    const countAll = allCaptainTasks.length;
    const count13 = allCaptainTasks.filter(t => t.current_list_title.includes('13')).length;
    const count11 = allCaptainTasks.filter(t => t.current_list_title.includes('11')).length;
    const count12 = allCaptainTasks.filter(t => t.current_list_title.includes('12')).length;
    const count09 = allCaptainTasks.filter(t => t.current_list_title.includes('09')).length;
    const count10 = allCaptainTasks.filter(t => t.current_list_title.includes('10')).length;

    document.getElementById('count-filter-all').textContent = countAll;
    document.getElementById('count-filter-13').textContent = count13;
    document.getElementById('count-filter-11').textContent = count11;
    document.getElementById('count-filter-12').textContent = count12;
    document.getElementById('count-filter-09').textContent = count09;
    document.getElementById('count-filter-10').textContent = count10;

    filtersContainer.querySelectorAll('.filter-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        filtersContainer.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentListFilter = btn.dataset.filter;
        renderStep1Tasks();
      });
    });
  }

  function renderStep1Tasks() {
    const container = document.getElementById('step-1-tasks-list');
    if (!allCaptainTasks.length) {
      container.innerHTML = '<div class="status-msg">Geen kapiteinstaken gevonden in de lijsten.</div>';
      return;
    }

    const filteredTasks = (currentListFilter === 'all')
      ? allCaptainTasks
      : allCaptainTasks.filter(t => t.current_list_title.includes(currentListFilter.split('.')[0]));

    if (filteredTasks.length === 0) {
      container.innerHTML = '<div class="status-msg">Geen taken in deze lijst.</div>';
      return;
    }

    container.innerHTML = filteredTasks.map((t) => {
      const isSelected = selectedTasks.some(st => st.title === t.title);
      return `
        <div class="task-select-item ${isSelected ? 'selected' : ''}" data-title="${t.title}">
          <input type="checkbox" ${isSelected ? 'checked' : ''}>
          <div class="task-select-item-info">
            <div class="task-select-item-title">${t.title}</div>
            <div class="task-select-item-notes"><span class="tag" style="font-size:10px; padding:1px 5px;">${t.current_list_title}</span> ${t.notes ? '• ' + t.notes : ''}</div>
          </div>
        </div>
      `;
    }).join('');

    // Checkbox click handlers
    container.querySelectorAll('.task-select-item').forEach(el => {
      el.addEventListener('click', (e) => {
        const title = el.dataset.title;
        const chk = el.querySelector('input[type="checkbox"]');
        if (e.target !== chk) chk.checked = !chk.checked;
        
        const task = allCaptainTasks.find(t => t.title === title);
        if (chk.checked) {
          el.classList.add('selected');
          if (!selectedTasks.some(st => st.title === task.title)) selectedTasks.push(task);
        } else {
          el.classList.remove('selected');
          selectedTasks = selectedTasks.filter(st => st.title !== task.title);
        }
        updateStep1Count();
      });
    });

    updateStep1Count();
  }

  function updateStep1Count() {
    document.getElementById('selected-tasks-count').textContent = `${selectedTasks.length} taken geselecteerd`;
  }

  document.getElementById('btn-select-all-tasks').addEventListener('click', () => {
    const filteredTasks = (currentListFilter === 'all')
      ? allCaptainTasks
      : allCaptainTasks.filter(t => t.current_list_title.includes(currentListFilter.split('.')[0]));

    filteredTasks.forEach(t => {
      if (!selectedTasks.some(st => st.title === t.title)) selectedTasks.push(t);
    });
    renderStep1Tasks();
  });

  document.getElementById('btn-deselect-all-tasks').addEventListener('click', () => {
    const filteredTasks = (currentListFilter === 'all')
      ? allCaptainTasks
      : allCaptainTasks.filter(t => t.current_list_title.includes(currentListFilter.split('.')[0]));

    const filteredTitles = new Set(filteredTasks.map(t => t.title));
    selectedTasks = selectedTasks.filter(t => !filteredTitles.has(t.title));
    renderStep1Tasks();
  });

  document.getElementById('btn-step-1-next').addEventListener('click', () => {
    if (selectedTasks.length < 2) {
      showToast('Selecteer minimaal 2 taken om te verdelen!', true);
      return;
    }
    setWizardStep(2);
    initPointsStep(2, 'roy');
  });

  // --- STAP 2 & 3: Points Allocation (1000pt) ---
  function initPointsStep(stepNum, player) {
    const grid = document.getElementById(`step-${stepNum}-points-grid`);
    const initialPts = Math.floor(1000 / selectedTasks.length);
    const remainder = 1000 - (initialPts * selectedTasks.length);

    const pointsObj = (player === 'roy') ? royPoints : karenPoints;

    // Reset or set default points if empty
    selectedTasks.forEach((t, i) => {
      if (pointsObj[t.title] === undefined) {
        pointsObj[t.title] = initialPts + (i === 0 ? remainder : 0);
      }
    });

    function renderPointsGrid() {
      grid.innerHTML = selectedTasks.map((t, idx) => `
        <div class="point-task-row">
          <div class="point-task-info">
            <div class="point-task-title">${t.title}</div>
            <div class="point-task-notes">${t.notes || ''}</div>
          </div>
          <div class="point-controls">
            <button class="btn btn-sm btn-outline btn-pt-minus" data-title="${t.title}">-5</button>
            <input type="number" class="point-input" data-title="${t.title}" value="${pointsObj[t.title] || 0}" min="0" max="1000">
            <button class="btn btn-sm btn-outline btn-pt-plus" data-title="${t.title}">+5</button>
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

      grid.querySelectorAll('.btn-pt-plus').forEach(btn => {
        btn.addEventListener('click', () => {
          const t = btn.dataset.title;
          pointsObj[t] = (pointsObj[t] || 0) + 5;
          renderPointsGrid();
        });
      });

      grid.querySelectorAll('.btn-pt-minus').forEach(btn => {
        btn.addEventListener('click', () => {
          const t = btn.dataset.title;
          pointsObj[t] = Math.max(0, (pointsObj[t] || 0) - 5);
          renderPointsGrid();
        });
      });

      updateBudgetStatus(stepNum, player);
    }

    renderPointsGrid();
  }

  function updateBudgetStatus(stepNum, player) {
    const pointsObj = (player === 'roy') ? royPoints : karenPoints;
    const totalAssigned = Object.values(pointsObj).reduce((sum, v) => sum + (parseInt(v) || 0), 0);
    const remaining = 1000 - totalAssigned;

    const textEl = document.getElementById(`${player}-budget-text`);
    const fillEl = document.getElementById(`${player}-budget-progress`);

    textEl.textContent = `${totalAssigned} / 1000 punten verdeeld (${remaining >= 0 ? remaining + ' over' : Math.abs(remaining) + ' te veel!'})`;
    
    const pct = Math.min(100, Math.max(0, (totalAssigned / 1000) * 100));
    fillEl.style.width = `${pct}%`;

    fillEl.className = 'progress-bar-fill';
    if (totalAssigned > 1000) fillEl.classList.add('danger');
    else if (totalAssigned === 1000) fillEl.style.background = '#3fb950';
  }

  document.getElementById('btn-step-2-prev').addEventListener('click', () => setWizardStep(1));
  document.getElementById('btn-step-2-next').addEventListener('click', () => {
    setWizardStep(3);
    initPointsStep(3, 'karen');
  });

  document.getElementById('btn-step-3-prev').addEventListener('click', () => setWizardStep(2));
  document.getElementById('btn-step-3-next').addEventListener('click', () => {
    calculateAverages();
    setWizardStep(4);
  });

  // --- STAP 4: Calculate & Render Averages ---
  function calculateAverages() {
    averageScores = selectedTasks.map(t => {
      const r = parseInt(royPoints[t.title]) || 0;
      const k = parseInt(karenPoints[t.title]) || 0;
      const avg = Math.round(((r + k) / 2) * 10) / 10;
      return {
        task: t,
        title: t.title,
        notes: t.notes,
        royPts: r,
        karenPts: k,
        avgPts: avg
      };
    });

    // Sort descending by average points (zwaarste taken bovenaan)
    averageScores.sort((a, b) => b.avgPts - a.avgPts);

    const tbody = document.getElementById('step-4-averages-tbody');
    tbody.innerHTML = averageScores.map(item => `
      <tr>
        <td><strong>${item.title}</strong><br><small style="color:var(--text-muted)">${item.notes || ''}</small></td>
        <td style="color:var(--roy-color); font-weight:700;">${item.royPts} pt</td>
        <td style="color:var(--karen-color); font-weight:700;">${item.karenPts} pt</td>
        <td><span class="tag" style="font-size:12px; font-weight:700;">⭐ ${item.avgPts} pt</span></td>
      </tr>
    `).join('');
  }

  document.getElementById('btn-step-4-prev').addEventListener('click', () => setWizardStep(3));
  document.getElementById('btn-step-4-next').addEventListener('click', () => {
    setWizardStep(5);
    initStep5Draft();
  });

  // --- STAP 5: Draft / Keuzerondes ---
  function initStep5Draft() {
    document.getElementById('starter-choice-box').style.display = 'flex';
    document.getElementById('draft-arena').style.display = 'none';

    availablePool = [...averageScores];
    royChosenTasks = [];
    karenChosenTasks = [];
    royTotalScore = 0;
    karenTotalScore = 0;
  }

  function startDraft(starter) {
    currentTurn = starter;
    document.getElementById('starter-choice-box').style.display = 'none';
    document.getElementById('draft-arena').style.display = 'block';
    renderDraftArena();
  }

  document.getElementById('btn-start-roy').addEventListener('click', () => startDraft('roy'));
  document.getElementById('btn-start-karen').addEventListener('click', () => startDraft('karen'));

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
    // Wie aan de beurt is blijft kiezen zolang diegene MINDER punten heeft dan de ander.
    // Zodra diegene meer of gelijk heeft, wisselt de beurt naar de speler met de minste punten!
    if (royTotalScore < karenTotalScore) {
      currentTurn = 'roy';
    } else if (karenTotalScore < royTotalScore) {
      currentTurn = 'karen';
    } else {
      // Gelijk aantal punten: wissel van beurt
      currentTurn = (currentTurn === 'roy') ? 'karen' : 'roy';
    }

    renderDraftArena();
  }

  function renderDraftArena() {
    const isKaren = (currentTurn === 'karen');
    const banner = document.getElementById('turn-banner');
    banner.className = `turn-banner ${isKaren ? 'karen-turn' : ''}`;
    
    document.getElementById('turn-text').textContent = isKaren ? 'Karen mag kiezen' : 'Roy mag kiezen';
    document.getElementById('turn-subtext').textContent = isKaren 
      ? `Karen heeft ${karenTotalScore.toFixed(1)} pt vs Roy ${royTotalScore.toFixed(1)} pt.`
      : `Roy heeft ${royTotalScore.toFixed(1)} pt vs Karen ${karenTotalScore.toFixed(1)} pt.`;

    // Scores & Balance
    document.getElementById('roy-current-pts').textContent = `${royTotalScore.toFixed(1)} pt`;
    document.getElementById('roy-tasks-count').textContent = `${royChosenTasks.length} taken`;

    document.getElementById('karen-current-pts').textContent = `${karenTotalScore.toFixed(1)} pt`;
    document.getElementById('karen-tasks-count').textContent = `${karenChosenTasks.length} taken`;

    const totalAssigned = (royTotalScore + karenTotalScore) || 1;
    const royPct = Math.round((royTotalScore / totalAssigned) * 100);
    const karenPct = 100 - royPct;

    document.getElementById('balance-fill-roy').style.width = `${royPct}%`;
    document.getElementById('balance-fill-karen').style.width = `${karenPct}%`;

    // Available Tasks
    document.getElementById('available-tasks-count').textContent = availablePool.length;
    const availableList = document.getElementById('available-tasks-list');
    
    if (availablePool.length === 0) {
      availableList.innerHTML = '<div class="status-msg success">🎉 Alle taken zijn verdeeld!</div>';
      document.getElementById('btn-step-5-finish').style.display = 'inline-flex';
    } else {
      document.getElementById('btn-step-5-finish').style.display = 'none';
      availableList.innerHTML = availablePool.map(item => `
        <div class="draft-pick-item" data-title="${item.title}">
          <div>
            <strong>${item.title}</strong>
            <div style="font-size:11px; color:var(--text-muted)">${item.notes || ''}</div>
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

    // Chosen Tasks
    document.getElementById('roy-chosen-list').innerHTML = royChosenTasks.map(i => `
      <div class="chosen-item">
        <span>${i.title}</span>
        <strong style="color:var(--roy-color)">${i.avgPts} pt</strong>
      </div>
    `).join('');

    document.getElementById('karen-chosen-list').innerHTML = karenChosenTasks.map(i => `
      <div class="chosen-item">
        <span>${i.title}</span>
        <strong style="color:var(--karen-color)">${i.avgPts} pt</strong>
      </div>
    `).join('');
  }

  document.getElementById('btn-step-5-prev').addEventListener('click', () => setWizardStep(4));
  document.getElementById('btn-step-5-finish').addEventListener('click', () => {
    setWizardStep(6);
    renderStep6Finale();
  });

  // --- STAP 6: Finale Summary & Google Tasks Apply ---
  function renderStep6Finale() {
    document.getElementById('final-roy-stats').textContent = `${royChosenTasks.length} taken | ${royTotalScore.toFixed(1)} pt`;
    document.getElementById('final-karen-stats').textContent = `${karenChosenTasks.length} taken | ${karenTotalScore.toFixed(1)} pt`;

    document.getElementById('final-roy-list').innerHTML = royChosenTasks.map(i => `
      <li>
        <span>${i.title}</span>
        <strong style="color:var(--roy-color)">${i.avgPts} pt</strong>
      </li>
    `).join('');

    document.getElementById('final-karen-list').innerHTML = karenChosenTasks.map(i => `
      <li>
        <span>${i.title}</span>
        <strong style="color:var(--karen-color)">${i.avgPts} pt</strong>
      </li>
    `).join('');
  }

  document.getElementById('btn-step-6-prev').addEventListener('click', () => setWizardStep(5));

  document.getElementById('btn-apply-division-google').addEventListener('click', async () => {
    const btn = document.getElementById('btn-apply-division-google');
    btn.disabled = true;
    btn.textContent = 'Bezig met synchroniseren naar Google Tasks...';
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
        btn.textContent = '✓ Gesynchroniseerd met Google Tasks!';
        btn.style.background = '#238636';
        loadJsonExport();
      } else {
        throw new Error(data.error || 'Onbekende fout');
      }
    } catch (e) {
      showToast('Fout bij synchroniseren: ' + e.message, true);
      btn.disabled = false;
      btn.textContent = 'Toepassen & Syncen naar Google Tasks! 🚀';
    }
  });

});
