const state = {
  datasetId: null,
  filename: null,
  profile: null,
  messages: [],
  latestAnswer: null,
  agent: null,
  backendWakeup: {
    visible: false,
    consecutiveFailures: 0,
    silentFailures: 0,
    lastSuccessAt: 0,
    lastTroubleAt: 0,
    retrying: false,
  },
};

const $ = (id) => document.getElementById(id);

const refs = {
  fileInput: $('fileInput'),
  uploadButton: $('uploadButton'),
  demoButton: $('demoButton'),
  dropZone: $('dropZone'),
  datasetName: $('datasetName'),
  sheetSelector: $('sheetSelector'),
  rowCount: $('rowCount'),
  colCount: $('colCount'),
  metricCount: $('metricCount'),
  dateCount: $('dateCount'),
  suggestions: $('suggestions'),
  agentMode: $('agentMode'),
  heroMetric: $('heroMetric'),
  heroDim: $('heroDim'),
  statusChip: $('statusChip'),
  kpiGrid: $('kpiGrid'),
  warnings: $('warnings'),
  columnsWrap: $('columnsWrap'),
  previewTable: $('previewTable'),
  chatWindow: $('chatWindow'),
  chatForm: $('chatForm'),
  questionInput: $('questionInput'),
  insightPanel: $('insightPanel'),
  reportButton: $('reportButton'),
  exportChatButton: $('exportChatButton'),
  focusChatButton: $('focusChatButton'),
  clearChatButton: $('clearChatButton'),
  themeToggle: $('themeToggle'),
  themeLabel: $('themeLabel'),
  toast: $('toast'),
  backendWakeup: $('backendWakeup'),
  backendWakeupRetry: $('backendWakeupRetry'),
};

const API_BASE_URL = normalizeApiBaseUrl(
  window.INSIGHTAGENT_API_BASE_URL ||
  document.querySelector('meta[name="insightagent-api-base-url"]')?.content ||
  ''
);

function normalizeApiBaseUrl(value) {
  return String(value || '').trim().replace(/\/$/, '');
}

function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return API_BASE_URL ? `${API_BASE_URL}${normalizedPath}` : normalizedPath;
}

initTheme();
wireEvents();
loadAgentStatus();
silentWakeBackend();

function avatarHtml(label = 'IA') {
  if (label === 'Tú') {
    return '<div class="avatar user-avatar">Tú</div>';
  }

  return `
    <div class="avatar clean-avatar">
      <img src="/static/logo.png" class="mini-logo" alt="InsightAgent">
    </div>
  `;
}

function wireEvents() {
  refs.uploadButton.addEventListener('click', () => refs.fileInput.click());
  refs.fileInput.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    if (file) uploadFile(file);
  });
  refs.demoButton.addEventListener('click', loadDemo);
  refs.chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const question = refs.questionInput.value.trim();
    if (question) askQuestion(question);
  });
  refs.focusChatButton.addEventListener('click', () => refs.questionInput.focus());
  refs.reportButton.addEventListener('click', exportReport);
  if (refs.exportChatButton) refs.exportChatButton.addEventListener('click', exportFullChat);
  refs.clearChatButton.addEventListener('click', clearChat);
  refs.themeToggle.addEventListener('click', toggleTheme);
  if (refs.backendWakeupRetry) refs.backendWakeupRetry.addEventListener('click', retryBackendWakeup);

  ['dragenter', 'dragover'].forEach((eventName) => {
    refs.dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      refs.dropZone.classList.add('drop-active');
    });
  });
  ['dragleave', 'drop'].forEach((eventName) => {
    refs.dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      refs.dropZone.classList.remove('drop-active');
    });
  });
  refs.dropZone.addEventListener('drop', (event) => {
    const file = event.dataTransfer.files?.[0];
    if (file) uploadFile(file);
  });
}

function initTheme() {
  const saved = localStorage.getItem('insightagent-theme') || document.documentElement.dataset.theme || 'dark';
  applyTheme(saved === 'light' ? 'light' : 'dark', false);
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

function applyTheme(theme, persist = true) {
  const normalized = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = normalized;
  if (persist) localStorage.setItem('insightagent-theme', normalized);
  const isDark = normalized === 'dark';
  refs.themeToggle.setAttribute('aria-pressed', String(isDark));
  refs.themeLabel.textContent = isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
  refs.themeToggle.title = isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
}

async function loadAgentStatus() {
  try {
    const data = await api('/health', {}, { requestKind: 'health', quiet: true });
    state.agent = data.agent;
    if (data.agent?.llm_enabled) {
      const primary = data.agent.primary_provider || data.agent.provider || 'LLM';
      const model = data.agent?.model || 'modelo activo';
      const fallbacks = (data.agent.available_providers || []).filter((item) => item !== primary);
      const fallbackText = fallbacks.length ? ` · fallback: ${fallbacks.join(' → ')}` : '';
      refs.agentMode.textContent = `Agente activo: ${primary} · ${model}${fallbackText}`;
    } else {
      refs.agentMode.textContent = 'Análisis local seguro';
    }
  } catch (_) {
    refs.agentMode.textContent = 'Análisis local seguro';
  }
}

async function uploadFile(file) {
  setLoading(true, 'Subiendo y analizando archivo...');
  const form = new FormData();
  form.append('file', file);
  try {
    const data = await api('/api/upload', { method: 'POST', body: form });
    setDataset(data);
    showToast(data.mode === 'document' ? 'Archivo cargado en modo documento.' : 'Archivo cargado correctamente.', 'success');
  } catch (error) {
    showToast(error.message || 'No pude cargar el archivo.', 'error');
  } finally {
    setLoading(false);
  }
}

async function loadDemo() {
  setLoading(true, 'Cargando datos de ejemplo...');
  try {
    const data = await api('/api/demo', { method: 'POST' });
    setDataset(data);
    showToast('Datos de ejemplo listos.', 'success');
  } catch (error) {
    showToast(error.message || 'No pude cargar los datos de ejemplo.', 'error');
  } finally {
    setLoading(false);
  }
}

function setDataset(data) {
  state.datasetId = data.dataset_id;
  state.filename = data.filename;
  state.profile = data.profile;
  state.mode = data.mode || data.profile?.mode || null;
  state.messages = [];
  state.latestAnswer = null;
  renderProfile();
  clearChat(true);
  const firstPrompt = data.profile.suggested_questions?.[0] || (data.mode === 'document' ? 'Resume el contenido principal del archivo.' : 'Dame un resumen ejecutivo de este conjunto de datos.');
  refs.questionInput.value = firstPrompt;
}

async function askQuestion(question) {
  if (!state.datasetId) {
    showToast('Primero carga un conjunto de datos.', 'error');
    return;
  }
  refs.questionInput.value = '';
  const askedAt = new Date().toISOString();
  appendMessage('user', question);
  state.messages.push({ role: 'user', content: question, timestamp: askedAt });
  const typingId = appendTyping();
  try {
    const answer = await api('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: state.datasetId, question }),
    });
    removeTyping(typingId);
    answer.timestamp = answer.timestamp || new Date().toISOString();
    state.latestAnswer = answer;
    state.messages.push({ role: 'assistant', answer, timestamp: answer.timestamp });
    appendAssistant(answer);
    renderInsight(answer);
  } catch (error) {
    removeTyping(typingId);
    const errorMessage = error.message || 'No pude analizar esa pregunta.';
    appendMessage('assistant', errorMessage);
    state.messages.push({ role: 'assistant', content: errorMessage, error: true, timestamp: new Date().toISOString() });
    showToast(error.message || 'Falló el análisis.', 'error');
  }
}

async function api(path, options = {}, meta = {}) {
  const requestKind = meta.requestKind || 'real';
  const quiet = Boolean(meta.quiet);
  const isHealth = requestKind === 'health';
  let response;
  try {
    response = await fetch(apiUrl(path), options);
  } catch (error) {
    if (isNetworkFailure(error)) {
      notifyBackendTrouble({ source: requestKind, quiet: quiet || isHealth });
      throw new Error('No pude conectar con el servicio. Puede estar iniciándose; intenta nuevamente en unos segundos.');
    }
    throw error;
  }
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();

  if (response.ok) {
    notifyBackendRecovered({ source: requestKind });
    return data;
  }

  if (isTransientBackendStatus(response.status)) {
    notifyBackendTrouble({ source: requestKind, status: response.status, quiet });
    throw new Error('El servicio está preparándose. Intenta nuevamente en unos segundos.');
  }

  // 400, 401, 403, 404 and validation errors are real application states,
  // not backend wake-up failures. Keep their original message.
  const detail = data?.detail || `Solicitud fallida (${response.status})`;
  throw new Error(detail);
}

function isTransientBackendStatus(status) {
  return [502, 503, 504].includes(Number(status));
}

function isNetworkFailure(error) {
  return error instanceof TypeError || error?.name === 'AbortError' || /Failed to fetch|NetworkError|Load failed/i.test(String(error?.message || ''));
}

async function silentWakeBackend() {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(apiUrl('/health'), {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
    });
    if (response.ok) {
      notifyBackendRecovered({ source: 'silent-health' });
      return true;
    }
    if (isTransientBackendStatus(response.status)) {
      state.backendWakeup.silentFailures += 1;
    }
  } catch (_) {
    state.backendWakeup.silentFailures += 1;
  } finally {
    window.clearTimeout(timer);
  }
  return false;
}

function notifyBackendTrouble({ source = 'real', status = null, quiet = false } = {}) {
  state.backendWakeup.lastTroubleAt = Date.now();
  if (quiet || source === 'health' || source === 'silent-health') {
    state.backendWakeup.silentFailures += 1;
    return;
  }

  state.backendWakeup.consecutiveFailures += 1;
  showBackendWakeup(status);
}

function notifyBackendRecovered({ source = 'real' } = {}) {
  state.backendWakeup.lastSuccessAt = Date.now();
  state.backendWakeup.consecutiveFailures = 0;
  state.backendWakeup.silentFailures = 0;

  // Any successful real request means old wake-up warnings are stale.
  if (source !== 'health' || state.backendWakeup.visible) {
    hideBackendWakeup();
  }
}

function showBackendWakeup(status = null) {
  if (!refs.backendWakeup) return;
  const transient = status ? ` Código temporal: ${status}.` : '';
  const copy = refs.backendWakeup.querySelector('.backend-wakeup-copy span');
  if (copy) {
    copy.textContent = `El backend gratuito puede tardar unos segundos si estuvo inactivo.${transient}`;
  }
  refs.backendWakeup.classList.remove('hidden');
  refs.backendWakeup.classList.add('show');
  state.backendWakeup.visible = true;
}

function hideBackendWakeup() {
  if (!refs.backendWakeup) return;
  refs.backendWakeup.classList.remove('show');
  refs.backendWakeup.classList.add('hidden');
  state.backendWakeup.visible = false;
}

async function retryBackendWakeup() {
  if (state.backendWakeup.retrying) return;
  state.backendWakeup.retrying = true;
  if (refs.backendWakeupRetry) {
    refs.backendWakeupRetry.disabled = true;
    refs.backendWakeupRetry.textContent = 'Reintentando...';
  }
  try {
    const response = await fetch(apiUrl('/health'), { method: 'GET', cache: 'no-store' });
    if (response.ok) {
      notifyBackendRecovered({ source: 'manual-retry' });
      showToast('Servicio listo.', 'success');
    } else if (isTransientBackendStatus(response.status)) {
      showBackendWakeup(response.status);
    } else {
      showToast(`El servicio respondió con estado ${response.status}.`, 'error');
    }
  } catch (error) {
    if (isNetworkFailure(error)) showBackendWakeup();
    else showToast(error.message || 'No pude contactar el servicio.', 'error');
  } finally {
    state.backendWakeup.retrying = false;
    if (refs.backendWakeupRetry) {
      refs.backendWakeupRetry.disabled = false;
      refs.backendWakeupRetry.textContent = 'Reintentar';
    }
  }
}

function renderProfile() {
  const profile = state.profile;
  if (!profile) return;

  refs.datasetName.textContent = state.filename || 'Conjunto de datos';
  refs.rowCount.textContent = formatNumber(profile.rows);
  refs.colCount.textContent = formatNumber(profile.columns_count);
  refs.metricCount.textContent = formatNumber(profile.numeric_columns.length);
  refs.dateCount.textContent = formatNumber(profile.date_columns.length);

  const isDocument = profile.mode === 'document';

  if (refs.heroMetric) {
    refs.heroMetric.textContent = isDocument ? 'Documento' : (profile.numeric_columns[0] || 'No detectada');
  }

  if (refs.heroDim) {
    refs.heroDim.textContent = isDocument ? 'Contenido' : (profile.categorical_columns[0] || 'No detectada');
  }

  refs.statusChip.innerHTML = '<span class="status-dot"></span>Datos listos';
  refs.statusChip.classList.add('ready');

  refs.kpiGrid.classList.remove('empty-state');
  refs.kpiGrid.innerHTML = isDocument ? [
    kpiCard('Modo', 'Documento'),
    kpiCard('Fragmentos', formatNumber(profile.rows)),
    kpiCard('Contenido', 'Chat'),
    kpiCard('Análisis avanzado', 'No aplicado'),
  ].join('') : [
    kpiCard('Filas', formatNumber(profile.rows)),
    kpiCard('Columnas', formatNumber(profile.columns_count)),
    kpiCard('Métricas numéricas', formatNumber(profile.numeric_columns.length)),
    kpiCard('Celdas vacías', `${formatNumber(profile.missing_pct)}%`),
  ].join('');

  refs.warnings.innerHTML = (profile.warnings || []).map((warning) => `<div class="warning-item">${escapeHtml(warning)}</div>`).join('');
  renderSheetSelector(profile);
  renderColumns(profile.columns || []);
  renderSuggestions(profile.suggested_questions || []);
  renderPreview(profile.preview || []);
}

function kpiCard(label, value) {
  return `<div class="kpi-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function renderSheetSelector(profile) {
  if (!refs.sheetSelector) return;
  const workbook = profile.workbook || null;
  const sheets = workbook?.sheets || [];
  if (!workbook?.is_workbook || !sheets.length) {
    refs.sheetSelector.classList.add('hidden');
    refs.sheetSelector.innerHTML = '';
    return;
  }

  const active = workbook.active_sheet || '';
  const selectable = sheets.filter((sheet) => sheet.selectable);
  const options = selectable.map((sheet) => {
    const selected = sheet.name === active ? 'selected' : '';
    const label = `${sheet.name} · ${formatNumber(sheet.rows || 0)} filas`;
    return `<option value="${escapeAttr(sheet.name)}" ${selected}>${escapeHtml(label)}</option>`;
  }).join('');
  const activeSheet = sheets.find((sheet) => sheet.name === active) || selectable[0] || sheets[0];
  const meta = activeSheet
    ? `${formatNumber(activeSheet.rows || 0)} filas · ${formatNumber(activeSheet.columns_count || 0)} columnas · encabezados en fila ${escapeHtml(String(activeSheet.header_row || 'n/a'))}`
    : '';
  const unavailable = sheets.filter((sheet) => !sheet.selectable).length;
  const unavailableText = unavailable ? `<div class="sheet-hint">${unavailable} hoja${unavailable === 1 ? '' : 's'} no se activaron porque parecen auxiliares, vacías o documentales.</div>` : '';

  refs.sheetSelector.classList.remove('hidden');
  refs.sheetSelector.innerHTML = `
    <div class="sheet-control-label">Hoja activa</div>
    <select id="activeSheetSelect" class="sheet-select" ${selectable.length <= 1 ? 'disabled' : ''}>
      ${options}
    </select>
    <div class="sheet-meta">${escapeHtml(meta)}</div>
    ${unavailableText}
  `;
  const select = refs.sheetSelector.querySelector('#activeSheetSelect');
  if (select) {
    select.addEventListener('change', (event) => {
      const sheetName = event.target.value;
      if (sheetName && sheetName !== active) switchSheet(sheetName);
    });
  }
}

async function switchSheet(sheetName) {
  if (!state.datasetId) return;
  setLoading(true, `Cambiando a ${sheetName}...`);
  try {
    const data = await api(`/api/datasets/${state.datasetId}/sheet`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sheet_name: sheetName }),
    });
    setDataset(data);
    showToast(`Hoja activa: ${sheetName}`, 'success');
  } catch (error) {
    showToast(error.message || 'No pude cambiar de hoja.', 'error');
  } finally {
    setLoading(false);
  }
}

function renderSuggestions(prompts) {
  if (!prompts.length) {
    refs.suggestions.innerHTML = '<div class="muted-list">Aún no hay sugerencias.</div>';
    return;
  }
  refs.suggestions.innerHTML = prompts.map((prompt) => `<button class="suggestion-btn" data-prompt="${escapeAttr(prompt)}">${escapeHtml(prompt)}</button>`).join('');
  refs.suggestions.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      refs.questionInput.value = button.dataset.prompt;
      refs.questionInput.focus();
    });
  });
}

function renderColumns(columns) {
  refs.columnsWrap.innerHTML = columns.slice(0, 18).map((col) => {
    const details = [];
    details.push(`${formatNumber(col.unique)} únicos`);
    if (col.missing_pct) details.push(`${formatNumber(col.missing_pct)}% vacío`);
    if (col.display_sum) details.push(`suma ${col.display_sum}`);
    return `<div class="column-pill"><strong>${escapeHtml(col.name)}</strong><span>${escapeHtml(tipoColumna(col.type))} · ${escapeHtml(details.join(' · '))}</span></div>`;
  }).join('');
}

function tipoColumna(type) {
  const map = { numerica: 'numérica', fecha: 'fecha', categorica: 'categórica', texto: 'texto', boolean: 'booleano', vacia: 'vacía', id: 'id' };
  return map[type] || type || 'desconocida';
}

function renderPreview(rows) {
  refs.previewTable.innerHTML = renderTable(rows);
}

function appendMessage(role, content) {
  const node = document.createElement('div');
  node.className = `message ${role === 'user' ? 'user-message' : 'assistant-message'}`;
  node.innerHTML = `${avatarHtml(role === 'user' ? 'Tú' : 'IA')}<div class="bubble"><p>${escapeHtml(content)}</p></div>`;
  refs.chatWindow.appendChild(node);
  scrollChat();
  return node;
}

function appendTyping() {
  const id = `typing-${Date.now()}`;
  const node = document.createElement('div');
  node.className = 'message assistant-message typing';
  node.dataset.typingId = id;
  node.innerHTML = `${avatarHtml('IA')}<div class="bubble"><strong>Analizando...</strong><p>Estoy seleccionando la herramienta adecuada y validando los resultados con cálculos reales.</p></div>`;
  refs.chatWindow.appendChild(node);
  scrollChat();
  return id;
}

function removeTyping(id) {
  const node = refs.chatWindow.querySelector(`[data-typing-id="${id}"]`);
  if (node) node.remove();
}

function appendAssistant(answer) {
  const node = document.createElement('div');
  node.className = 'message assistant-message';
  const kpis = answer.kpis?.length ? `<div class="message-kpis">${answer.kpis.map((item) => `<div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(String(item.value))}</strong></div>`).join('')}</div>` : '';
  const findings = answer.findings?.length ? `<div class="support-block"><div class="support-title">Hallazgos</div><ul>${answer.findings.slice(0, 5).map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>` : '';
  const table = answer.table?.length ? supportTable(answer, 6) : '';
  const dataNote = answer.calculation_note ? `<div class="calculation-note">${escapeHtml(answer.calculation_note)}</div>` : '';
  const agentTag = answer.agent ? `<div class="agent-tag">${escapeHtml(etiquetaAgente(answer.agent))}</div>` : '';
  node.innerHTML = `${avatarHtml('IA')}<div class="bubble"><strong>${escapeHtml(answer.title || 'Análisis')}</strong><p>${escapeHtml(answer.executive_summary || '')}</p>${dataNote}${kpis}${table}${findings}${agentTag}</div>`;
  refs.chatWindow.appendChild(node);
  scrollChat();
}

function etiquetaAgente(agent) {
  if (agent.llm_used) return `Agente activo: ${agent.provider} · ${agent.model}`;
  return 'Análisis local seguro';
}

function clearChat(silent = false) {
  const isDocument = state.profile?.mode === 'document';
  const title = state.profile ? (isDocument ? 'Archivo listo.' : 'Datos listos.') : 'Listo para analizar.';
  const message = state.profile
    ? (isDocument ? 'El archivo quedó listo para preguntas sobre su contenido.' : 'Escribe una pregunta concreta o selecciona una sugerencia.')
    : 'Sube un archivo o usa los datos de ejemplo para comenzar.';
  state.messages = [{
    role: 'assistant',
    content: `${title} ${message}`,
    system_notice: true,
    timestamp: new Date().toISOString(),
  }];
  state.latestAnswer = null;
  refs.chatWindow.innerHTML = `<div class="message assistant-message">${avatarHtml('IA')}<div class="bubble"><strong>${title}</strong><p>${message}</p></div></div>`;
  refs.insightPanel.innerHTML = '<p>El análisis más reciente aparecerá aquí con gráfico, tabla y recomendaciones.</p>';
  refs.insightPanel.classList.add('empty-state');
  scrollChat('auto');
  if (!silent) showToast('Conversación limpia.', 'success');
}

function renderInsight(answer) {
  refs.insightPanel.classList.remove('empty-state');
  const kpis = answer.kpis?.length ? `<div class="kpi-grid compact-grid">${answer.kpis.map((item) => kpiCard(item.label, item.value)).join('')}</div>` : '';
  const chart = answer.chart ? `<div class="chart-wrap">${renderChart(answer.chart)}</div>` : '';
  const table = answer.table?.length ? supportTable(answer, 12) : '';
  const findings = answer.findings?.length ? insightList('Hallazgos', answer.findings) : '';
  const recs = answer.recommendations?.length ? insightList('Recomendaciones', answer.recommendations) : '';
  const limits = answer.limitations?.length ? insightList('Limitaciones', answer.limitations) : '';
  const agent = answer.agent ? `<div class="agent-note">${escapeHtml(etiquetaAgente(answer.agent))}</div>` : '';
  const dataNote = answer.calculation_note ? `<div class="calculation-note wide">${escapeHtml(answer.calculation_note)}</div>` : '';
  refs.insightPanel.innerHTML = `<div class="insight-title">${escapeHtml(answer.title || 'Análisis')}</div><div class="insight-summary">${escapeHtml(answer.executive_summary || '')}</div>${dataNote}${agent}${kpis}${chart}${table}${findings}${recs}${limits}`;
}

function insightList(title, items) {
  return `<div class="insight-block"><h3>${escapeHtml(title)}</h3><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`;
}

function supportTable(answer, limit = 8) {
  const rows = (answer.table || []).slice(0, limit);
  const title = answer.table_title || 'Tabla de soporte';
  return `<div class="support-table"><div class="support-title">${escapeHtml(title)}</div>${renderTable(rows)}</div>`;
}

function renderTable(rows) {
  if (!rows || !rows.length) return '<div class="empty-state"><p>No hay filas para mostrar.</p></div>';
  const columns = Object.keys(rows[0]);
  return `<div class="table-wrap"><table><thead><tr>${columns.map((col) => `<th>${escapeHtml(prettyHeader(col))}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((col) => `<td>${escapeHtml(formatCell(row[col], col))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function renderChart(chart) {
  if (!chart?.data?.length) return '<div class="empty-state"><p>No hay datos suficientes para graficar.</p></div>';
  const type = chart.type || 'bar';
  if (type === 'pie') return renderPieChart(chart);
  if (type === 'scatter') return renderScatterChart(chart);
  // Histograma reutiliza barras pero con etiquetas de rango.
  return renderCartesianChart(chart, type === 'histogram' ? 'bar' : type);
}

function renderCartesianChart(chart, type = 'bar') {
  const data = chart.data.slice(0, 24);
  const xKey = chart.xKey;
  const yKey = chart.yKey;
  const values = data.map((row) => Number(row[yKey]) || 0);
  const labels = data.map((row) => String(row[xKey] ?? ''));
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = max - min || 1;
  const width = 520;
  const height = 300;
  const pad = { top: 22, right: 18, bottom: 56, left: 58 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const yScale = (value) => pad.top + (max - value) / range * innerH;
  const baseline = yScale(0);
  if (type === 'line') {
    const step = data.length > 1 ? innerW / (data.length - 1) : innerW;
    const points = values.map((value, index) => `${pad.left + step * index},${yScale(value)}`).join(' ');
    const dots = values.map((value, index) => `<circle class="chart-dot" cx="${pad.left + step * index}" cy="${yScale(value)}" r="4.5"><title>${escapeAttr(labels[index])}: ${formatNumber(value)}</title></circle>`).join('');
    return `<div class="chart-title">${escapeHtml(chart.title || '')}</div><svg class="svg-chart" viewBox="0 0 ${width} ${height}" role="img">${gridLines(width, pad, yScale, min, max)}<polyline class="chart-line" points="${points}" />${dots}${axisLabels(labels, width, height, pad)}</svg>`;
  }
  const gap = Math.max(6, Math.min(12, 180 / Math.max(data.length, 1)));
  const barW = Math.max(8, (innerW - gap * (data.length - 1)) / Math.max(data.length, 1));
  const bars = values.map((value, index) => {
    const x = pad.left + index * (barW + gap);
    const y = value >= 0 ? yScale(value) : baseline;
    const h = Math.abs(yScale(value) - baseline);
    return `<rect class="chart-bar" x="${x}" y="${y}" width="${barW}" height="${Math.max(2, h)}" rx="5"><title>${escapeAttr(labels[index])}: ${formatNumber(value)}</title></rect>`;
  }).join('');
  return `<div class="chart-title">${escapeHtml(chart.title || '')}</div><svg class="svg-chart" viewBox="0 0 ${width} ${height}" role="img">${gridLines(width, pad, yScale, min, max)}<line class="chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${baseline}" y2="${baseline}" />${bars}${axisLabels(labels, width, height, pad)}</svg>`;
}

function renderScatterChart(chart) {
  const data = chart.data.slice(0, 300);
  const xKey = chart.xKey;
  const yKey = chart.yKey;
  const points = data.map((row) => ({ x: Number(row[xKey]), y: Number(row[yKey]) })).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!points.length) return '<div class="empty-state"><p>No hay puntos válidos para la dispersión.</p></div>';
  const width = 520;
  const height = 300;
  const pad = { top: 22, right: 22, bottom: 56, left: 62 };
  const minX = Math.min(...points.map((p) => p.x));
  const maxX = Math.max(...points.map((p) => p.x));
  const minY = Math.min(...points.map((p) => p.y));
  const maxY = Math.max(...points.map((p) => p.y));
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const xRange = maxX - minX || 1;
  const yRange = maxY - minY || 1;
  const xScale = (v) => pad.left + ((v - minX) / xRange) * innerW;
  const yScale = (v) => pad.top + ((maxY - v) / yRange) * innerH;
  const dots = points.map((p) => `<circle class="scatter-dot" cx="${xScale(p.x)}" cy="${yScale(p.y)}" r="4"><title>${escapeAttr(xKey)}: ${formatNumber(p.x)} · ${escapeAttr(yKey)}: ${formatNumber(p.y)}</title></circle>`).join('');
  return `<div class="chart-title">${escapeHtml(chart.title || '')}</div><svg class="svg-chart" viewBox="0 0 ${width} ${height}" role="img"><line class="chart-grid" x1="${pad.left}" x2="${pad.left}" y1="${pad.top}" y2="${height - pad.bottom}"/><line class="chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}"/><text class="axis-label" x="${pad.left}" y="${height - 18}">${formatNumber(minX)}</text><text class="axis-label" x="${width - pad.right}" y="${height - 18}" text-anchor="end">${formatNumber(maxX)}</text><text class="axis-label" x="4" y="${height - pad.bottom}">${formatNumber(minY)}</text><text class="axis-label" x="4" y="${pad.top + 4}">${formatNumber(maxY)}</text>${dots}<text class="axis-label" x="${width / 2}" y="${height - 4}" text-anchor="middle">${escapeHtml(xKey)}</text><text class="axis-label" x="10" y="${height / 2}" transform="rotate(-90 10 ${height / 2})" text-anchor="middle">${escapeHtml(yKey)}</text></svg>`;
}

function renderPieChart(chart) {
  const xKey = chart.xKey;
  const yKey = chart.yKey;
  const data = chart.data.slice(0, 8).map((row) => ({ label: String(row[xKey] ?? ''), value: Math.max(0, Number(row[yKey]) || 0) })).filter((row) => row.value > 0);
  const total = data.reduce((sum, row) => sum + row.value, 0);
  if (!data.length || !total) return '<div class="empty-state"><p>No hay valores positivos para graficar participación.</p></div>';
  let cumulative = 0;
  const radius = 92;
  const cx = 130;
  const cy = 130;
  const slices = data.map((row, index) => {
    const start = cumulative / total;
    cumulative += row.value;
    const end = cumulative / total;
    return `<path class="chart-slice slice-${index}" d="${pieSlicePath(cx, cy, radius, start, end)}"><title>${escapeAttr(row.label)}: ${formatNumber(row.value)} (${formatNumber(row.value / total * 100)}%)</title></path>`;
  }).join('');
  const legend = data.map((row, index) => `<div class="chart-legend-item"><span class="legend-dot slice-bg-${index}"></span><strong>${escapeHtml(truncate(row.label, 28))}</strong><em>${formatNumber(row.value / total * 100)}%</em></div>`).join('');
  return `<div class="chart-title">${escapeHtml(chart.title || '')}</div><div class="pie-layout"><svg class="svg-chart pie-svg" viewBox="0 0 260 260" role="img">${slices}<circle class="pie-hole" cx="${cx}" cy="${cy}" r="48"/><text class="pie-center" x="${cx}" y="${cy - 5}" text-anchor="middle">Total</text><text class="pie-center-value" x="${cx}" y="${cy + 17}" text-anchor="middle">${formatNumber(total)}</text></svg><div class="chart-legend">${legend}</div></div>`;
}

function pieSlicePath(cx, cy, r, startPct, endPct) {
  const startAngle = startPct * Math.PI * 2 - Math.PI / 2;
  const endAngle = endPct * Math.PI * 2 - Math.PI / 2;
  const x1 = cx + r * Math.cos(startAngle);
  const y1 = cy + r * Math.sin(startAngle);
  const x2 = cx + r * Math.cos(endAngle);
  const y2 = cy + r * Math.sin(endAngle);
  const largeArc = endPct - startPct > 0.5 ? 1 : 0;
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
}

function gridLines(width, pad, yScale, min, max) {
  const ticks = [min, min + (max - min) / 2, max];
  return ticks.map((tick) => {
    const y = yScale(tick);
    return `<line class="chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}" /><text class="axis-label" x="4" y="${y + 4}">${formatNumber(tick)}</text>`;
  }).join('');
}

function axisLabels(labels, width, height, pad) {
  const maxLabels = 6;
  const step = Math.max(1, Math.ceil(labels.length / maxLabels));
  const innerW = width - pad.left - pad.right;
  return labels.map((label, index) => {
    if (index % step !== 0 && index !== labels.length - 1) return '';
    const x = pad.left + (labels.length > 1 ? (innerW / (labels.length - 1)) * index : innerW / 2);
    return `<text class="axis-label" x="${x}" y="${height - 16}" text-anchor="middle">${escapeHtml(truncate(label, 10))}</text>`;
  }).join('');
}


async function exportFullChat() {
  if (!state.profile && state.messages.length <= 1) {
    showToast('No hay conversación para exportar.', 'error');
    return;
  }
  try {
    const payload = await buildChatExportPayload();
    const html = buildChatExportHtml(payload);
    const filename = `insightagent-chat-${safeTimestamp()}.html`;
    downloadTextFile(filename, html, 'text/html;charset=utf-8');
    showToast('Chat exportado correctamente.', 'success');
  } catch (error) {
    showToast(error.message || 'No pude exportar el chat.', 'error');
  }
}

async function buildChatExportPayload() {
  const profile = state.profile || {};
  const logoSrc = await readLogoDataUrl();
  return {
    app: 'InsightAgent',
    export_type: 'chat_completo',
    exported_at: new Date().toISOString(),
    page_url: window.location.href,
    logo_src: logoSrc,
    user_agent: navigator.userAgent,
    dataset: {
      dataset_id: state.datasetId,
      filename: state.filename,
      mode: profile.mode || null,
      rows: profile.rows ?? null,
      columns_count: profile.columns_count ?? null,
      missing_pct: profile.missing_pct ?? null,
      numeric_columns: profile.numeric_columns || [],
      categorical_columns: profile.categorical_columns || [],
      date_columns: profile.date_columns || [],
      text_columns: profile.text_columns || [],
      warnings: profile.warnings || [],
    },
    agent: state.agent || null,
    profile,
    latest_answer: state.latestAnswer || null,
    messages: state.messages.map((message, index) => ({
      index: index + 1,
      ...message,
    })),
  };
}

function buildChatExportHtml(payload) {
  const dataset = payload.dataset || {};
  const messages = payload.messages || [];
  const rawJson = JSON.stringify(payload, null, 2);
  const messageHtml = messages.map(renderExportMessage).join('');
  const profileWarnings = dataset.warnings?.length
    ? `<ul>${dataset.warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
    : '<p>Sin advertencias registradas.</p>';

  return `<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Chat exportado - InsightAgent</title>
  <style>
    :root { color-scheme: dark; --bg:#0a0a0b; --card:#121214; --card2:#18181b; --text:#f4f4f5; --muted:#a1a1aa; --line:rgba(244,244,245,.14); --accent:#22c55e; --primary:#2563eb; }
    * { box-sizing:border-box; }
    body { margin:0; background:radial-gradient(circle at top right, rgba(37,99,235,.13), transparent 28vw), linear-gradient(180deg,#0a0a0b,#111113); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; line-height:1.55; }
    .page { max-width:1100px; margin:0 auto; padding:34px 22px 54px; }
    .topbar { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:22px; }
    .brand { display:flex; align-items:center; gap:14px; }
    .logo { width:46px; height:46px; border-radius:14px; object-fit:cover; border:1px solid var(--line); }
    h1 { margin:0; font-size:clamp(2rem,4vw,3.4rem); line-height:.95; letter-spacing:-.06em; }
    h2 { margin:0 0 12px; letter-spacing:-.03em; }
    h3 { margin:18px 0 8px; }
    .muted { color:var(--muted); }
    .grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:22px 0; }
    .card { background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.035)); border:1px solid var(--line); border-radius:22px; padding:18px; box-shadow:0 24px 70px rgba(0,0,0,.28); }
    .kpi span { display:block; color:var(--muted); font-size:.78rem; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }
    .kpi strong { display:block; margin-top:8px; font-size:1.45rem; letter-spacing:-.04em; }
    .pill { display:inline-flex; align-items:center; gap:8px; border:1px solid rgba(34,197,94,.28); background:rgba(34,197,94,.10); color:#bbf7d0; border-radius:999px; padding:8px 12px; font-weight:850; font-size:.82rem; }
    .message { display:grid; grid-template-columns:120px minmax(0,1fr); gap:14px; margin:14px 0; }
    .role { color:var(--muted); font-size:.8rem; font-weight:900; text-transform:uppercase; letter-spacing:.11em; padding-top:14px; }
    .bubble { background:rgba(255,255,255,.055); border:1px solid var(--line); border-radius:20px; padding:16px; }
    .user .bubble { background:linear-gradient(135deg,rgba(37,99,235,.26),rgba(79,70,229,.18)); border-color:rgba(96,165,250,.25); }
    .assistant .bubble { background:rgba(255,255,255,.05); }
    .notice .bubble { background:rgba(34,197,94,.08); border-color:rgba(34,197,94,.18); }
    .timestamp { color:var(--muted); font-size:.78rem; margin-top:10px; }
    .note { margin-top:12px; border-left:4px solid var(--accent); background:rgba(34,197,94,.10); color:#bbf7d0; padding:10px 12px; border-radius:14px; font-size:.9rem; font-weight:700; }
    .blocks { display:grid; gap:14px; margin-top:14px; }
    ul { margin:8px 0 0; padding-left:20px; }
    table { width:100%; border-collapse:collapse; font-size:.86rem; margin-top:10px; }
    th,td { border-bottom:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }
    th { color:#d4d4d8; background:rgba(255,255,255,.045); font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:16px; margin-top:10px; }
    .chart-wrap { background:rgba(255,255,255,.04); border:1px solid var(--line); border-radius:18px; padding:14px; margin-top:12px; overflow:hidden; }
    .svg-chart { width:100%; height:280px; display:block; overflow:visible; }
    .chart-title { font-weight:900; margin-bottom:10px; }
    .axis-label { fill:#a1a1aa; font-size:10px; }
    .chart-grid { stroke:rgba(244,244,245,.18); stroke-width:1; }
    .chart-bar { fill:#2563eb; opacity:.9; }
    .chart-line { fill:none; stroke:#60a5fa; stroke-width:3; }
    .chart-dot { fill:#22c55e; }
    details.raw { margin-top:24px; }
    details.raw summary { cursor:pointer; font-weight:900; }
    pre { white-space:pre-wrap; word-break:break-word; max-height:520px; overflow:auto; background:#050505; border:1px solid var(--line); border-radius:18px; padding:16px; color:#e5e7eb; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; }
    button { border:0; border-radius:14px; padding:10px 14px; font-weight:850; cursor:pointer; }
    .print { background:linear-gradient(135deg,#2563eb,#1d4ed8); color:white; }
    .secondary { background:rgba(255,255,255,.08); color:var(--text); border:1px solid var(--line); }
    @media (max-width:760px) { .grid { grid-template-columns:1fr 1fr; } .message { grid-template-columns:1fr; gap:6px; } .role { padding-top:0; } }
    @media print { body { background:white; color:#111827; } .card,.bubble,.chart-wrap,pre { box-shadow:none; background:white; border-color:#e5e7eb; } .muted,.timestamp,.role { color:#6b7280; } .actions, details.raw { display:none; } .page { max-width:none; padding:24px; } }
  </style>
</head>
<body>
  <main class="page">
    <div class="topbar">
      <div class="brand">
        <img src="${escapeAttr(payload.logo_src || '')}" class="logo" alt="InsightAgent" />
        <div>
          <div class="pill">Chat exportado</div>
          <h1>InsightAgent</h1>
          <p class="muted">Exportado el ${escapeHtml(formatExportDate(payload.exported_at))}</p>
        </div>
      </div>
      <div class="actions">
        <button class="print" onclick="window.print()">Imprimir / guardar PDF</button>
        <button class="secondary" onclick="copyRawJson()">Copiar JSON</button>
      </div>
    </div>

    <section class="card">
      <h2>Contexto del análisis</h2>
      <p class="muted">Archivo: <strong>${escapeHtml(dataset.filename || 'Sin archivo')}</strong> · Modo: <strong>${escapeHtml(dataset.mode || 'n/a')}</strong> · Agente: <strong>${escapeHtml(payload.agent?.provider || 'local')}</strong></p>
      <div class="grid">
        <div class="kpi card"><span>Filas</span><strong>${escapeHtml(formatNumber(dataset.rows))}</strong></div>
        <div class="kpi card"><span>Columnas</span><strong>${escapeHtml(formatNumber(dataset.columns_count))}</strong></div>
        <div class="kpi card"><span>Métricas</span><strong>${escapeHtml(formatNumber(dataset.numeric_columns?.length || 0))}</strong></div>
        <div class="kpi card"><span>Mensajes</span><strong>${escapeHtml(formatNumber(messages.length))}</strong></div>
      </div>
      <h3>Advertencias del archivo</h3>
      ${profileWarnings}
    </section>

    <section class="card" style="margin-top:18px">
      <h2>Conversación completa</h2>
      ${messageHtml || '<p class="muted">No hay mensajes registrados.</p>'}
    </section>

    <details class="raw">
      <summary>Datos técnicos para depuración</summary>
      <p class="muted">Puedes compartir este archivo completo o copiar este JSON en cualquier asistente de IA para revisar errores de interpretación, columnas, intención, cálculos y respuesta.</p>
      <pre id="rawJson">${escapeHtml(rawJson)}</pre>
    </details>
  </main>
  <script>
    function copyRawJson(){
      const text = document.getElementById('rawJson').innerText;
      navigator.clipboard.writeText(text).then(() => alert('JSON copiado.'));
    }
  </script>
</body>
</html>`;
}

function renderExportMessage(message) {
  const role = message.role || 'assistant';
  const timestamp = message.timestamp ? `<div class="timestamp">${escapeHtml(formatExportDate(message.timestamp))}</div>` : '';
  if (role === 'user') {
    return `<article class="message user"><div class="role">Usuario</div><div class="bubble"><p>${escapeHtml(message.content || '')}</p>${timestamp}</div></article>`;
  }
  if (message.answer) {
    return `<article class="message assistant"><div class="role">Agente</div><div class="bubble">${renderExportAnswer(message.answer)}${timestamp}</div></article>`;
  }
  const klass = message.system_notice ? 'message assistant notice' : 'message assistant';
  return `<article class="${klass}"><div class="role">Agente</div><div class="bubble"><p>${escapeHtml(message.content || '')}</p>${timestamp}</div></article>`;
}

function renderExportAnswer(answer) {
  const kpis = answer.kpis?.length ? `<div class="grid">${answer.kpis.map((item) => `<div class="kpi card"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(String(item.value))}</strong></div>`).join('')}</div>` : '';
  const note = answer.calculation_note ? `<div class="note">${escapeHtml(answer.calculation_note)}</div>` : '';
  const chart = answer.chart ? `<div class="chart-wrap">${renderChart(answer.chart)}</div>` : '';
  const table = answer.table?.length ? `<h3>${escapeHtml(answer.table_title || 'Tabla de soporte')}</h3>${renderTable(answer.table)}` : '';
  const findings = answer.findings?.length ? `<h3>Hallazgos</h3><ul>${answer.findings.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : '';
  const recommendations = answer.recommendations?.length ? `<h3>Recomendaciones</h3><ul>${answer.recommendations.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : '';
  const limitations = answer.limitations?.length ? `<h3>Limitaciones</h3><ul>${answer.limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : '';
  const agent = answer.agent ? `<div class="timestamp">${escapeHtml(etiquetaAgente(answer.agent))}</div>` : '';
  return `<h2>${escapeHtml(answer.title || 'Análisis')}</h2><p>${escapeHtml(answer.executive_summary || '')}</p>${note}${kpis}${chart}${table}${findings}${recommendations}${limitations}${agent}`;
}


async function readLogoDataUrl() {
  const logo = document.querySelector('.brand-logo');
  const src = logo?.getAttribute('src') || '/static/logo.png';
  try {
    const response = await fetch(src, { cache: 'force-cache' });
    if (!response.ok) throw new Error('No se pudo leer el logo.');
    const blob = await response.blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  } catch (_) {
    return '';
  }
}

function downloadTextFile(filename, content, mimeType = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function safeTimestamp() {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
}

function formatExportDate(value) {
  if (!value) return 'n/a';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

async function exportReport() {
  if (!state.profile) {
    showToast('Carga un conjunto de datos antes de exportar un reporte.', 'error');
    return;
  }
  const answer = state.latestAnswer;
  const profile = state.profile || {};
  const logoSrc = await readLogoDataUrl();
  const chart = answer?.chart ? `<section class="report-card"><h2>Visualización principal</h2>${renderChart(answer.chart)}</section>` : '';
  const table = answer?.table?.length ? `<section class="report-card"><h2>${escapeHtml(answer.table_title || 'Tabla de soporte')}</h2>${renderTable(answer.table)}</section>` : '';
  const findings = answer?.findings?.length ? `<section class="report-card"><h2>Hallazgos</h2><ul>${answer.findings.map((x) => `<li>${escapeHtml(x)}</li>`).join('')}</ul></section>` : '';
  const recommendations = answer?.recommendations?.length ? `<section class="report-card"><h2>Recomendaciones</h2><ul>${answer.recommendations.map((x) => `<li>${escapeHtml(x)}</li>`).join('')}</ul></section>` : '';
  const limitations = answer?.limitations?.length ? `<section class="report-card"><h2>Limitaciones</h2><ul>${answer.limitations.map((x) => `<li>${escapeHtml(x)}</li>`).join('')}</ul></section>` : '';
  const kpis = [
    ['Filas', formatNumber(profile.rows)],
    ['Columnas', formatNumber(profile.columns_count)],
    ['Métricas', formatNumber((profile.numeric_columns || []).length)],
    ['Celdas vacías', `${formatNumber(profile.missing_pct)}%`],
  ].concat((answer?.kpis || []).slice(0, 4).map((x) => [x.label, x.value]));
  const reportHtml = `<!doctype html><html lang="es"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>Reporte ejecutivo de InsightAgent</title><style>
    :root{--bg:#0a0a0b;--card:#121214;--card2:#18181b;--text:#f4f4f5;--muted:#a1a1aa;--line:rgba(244,244,245,.14);--accent:#22c55e;--primary:#2563eb;--surface:#121214}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,rgba(37,99,235,.16),transparent 30vw),linear-gradient(180deg,#0a0a0b,#111113);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;line-height:1.55}.page{max-width:1120px;margin:0 auto;padding:34px 22px 56px}.topbar{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:24px}.brand{display:flex;gap:14px;align-items:center}.logo{width:48px;height:48px;border-radius:14px;object-fit:cover;border:1px solid var(--line)}.pill{display:inline-flex;border:1px solid rgba(34,197,94,.25);background:rgba(34,197,94,.1);color:#bbf7d0;border-radius:999px;padding:7px 11px;font-weight:850;font-size:.82rem}h1{margin:10px 0 8px;font-size:clamp(2.2rem,5vw,4.3rem);line-height:.94;letter-spacing:-.07em}h2{margin:0 0 12px;letter-spacing:-.035em}.muted{color:var(--muted)}.actions{display:flex;gap:10px;flex-wrap:wrap}button{border:0;border-radius:14px;padding:10px 14px;font-weight:850;cursor:pointer}.print{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:white}.report-card{background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.035));border:1px solid var(--line);border-radius:24px;padding:20px;margin:16px 0;box-shadow:0 24px 70px rgba(0,0,0,.26)}.hero{padding:28px}.summary{font-size:1.08rem;max-width:860px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.kpi{background:rgba(255,255,255,.045);border:1px solid var(--line);border-radius:18px;padding:15px}.kpi span{display:block;color:var(--muted);font-size:.75rem;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.kpi strong{display:block;margin-top:8px;font-size:1.35rem}.note{border-left:4px solid var(--accent);background:rgba(34,197,94,.10);color:#bbf7d0;padding:12px 14px;border-radius:14px;font-weight:700}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:16px;margin-top:10px}table{width:100%;border-collapse:collapse;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}th{color:#d4d4d8;background:rgba(255,255,255,.045);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em}ul{margin:8px 0 0;padding-left:20px}.chart-title{font-weight:900;margin-bottom:10px}.svg-chart{width:100%;height:300px;display:block;overflow:visible}.axis-label{fill:#a1a1aa;font-size:10px}.chart-grid{stroke:rgba(244,244,245,.18);stroke-width:1}.chart-bar{fill:#2563eb;opacity:.9}.chart-line{fill:none;stroke:#60a5fa;stroke-width:3}.chart-dot{fill:#22c55e}.scatter-dot{fill:#60a5fa;opacity:.74}.pie-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,.75fr);gap:16px;align-items:center}.pie-svg{height:300px}.chart-slice{stroke:var(--surface);stroke-width:1.5}.slice-0{fill:#2563eb}.slice-1{fill:#22c55e}.slice-2{fill:#a855f7}.slice-3{fill:#f59e0b}.slice-4{fill:#06b6d4}.slice-5{fill:#ef4444}.slice-6{fill:#84cc16}.slice-7{fill:#64748b}.pie-hole{fill:var(--surface)}.pie-center{fill:var(--muted);font-size:12px;font-weight:800}.pie-center-value{fill:var(--text);font-size:16px;font-weight:900}.chart-legend{display:grid;gap:8px}.chart-legend-item{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:8px;font-size:.82rem}.chart-legend-item strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.chart-legend-item em{color:var(--muted);font-style:normal;font-weight:800}.legend-dot{width:10px;height:10px;border-radius:999px}.slice-bg-0{background:#2563eb}.slice-bg-1{background:#22c55e}.slice-bg-2{background:#a855f7}.slice-bg-3{background:#f59e0b}.slice-bg-4{background:#06b6d4}.slice-bg-5{background:#ef4444}.slice-bg-6{background:#84cc16}.slice-bg-7{background:#64748b}.footer{margin-top:24px;color:var(--muted);font-size:.86rem}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}.topbar{display:block}.actions{margin-top:14px}.pie-layout{grid-template-columns:1fr}}@media print{body{background:white;color:#111827}.report-card,.kpi{box-shadow:none;background:white;border-color:#e5e7eb}.muted,.footer{color:#6b7280}.actions{display:none}.page{max-width:none;padding:24px}.note{color:#166534;background:#ecfdf5}}
  </style></head><body><main class="page"><div class="topbar"><div class="brand">${logoSrc ? `<img class="logo" src="${logoSrc}" alt="InsightAgent" />` : ''}<div><div class="pill">Reporte ejecutivo</div><h1>InsightAgent</h1><p class="muted">${escapeHtml(state.filename || 'Conjunto de datos')} · ${escapeHtml(formatExportDate(new Date().toISOString()))}</p></div></div><div class="actions"><button class="print" onclick="window.print()">Imprimir / guardar PDF</button></div></div><section class="report-card hero"><h2>${escapeHtml(answer?.title || 'Análisis pendiente')}</h2><p class="summary">${escapeHtml(answer?.executive_summary || 'Haz una pregunta al agente para generar un análisis ejecutivo.')}</p>${answer?.calculation_note ? `<div class="note">${escapeHtml(answer.calculation_note)}</div>` : ''}</section><section class="report-card"><h2>Indicadores</h2><div class="grid">${kpis.map(([label,value]) => `<div class="kpi"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join('')}</div></section>${chart}${table}${findings}${recommendations}${limitations}<div class="footer">Generado por InsightAgent. Los cálculos se basan en el archivo cargado y en las herramientas seguras del sistema.</div></main></body></html>`;
  const win = window.open('', '_blank');
  win.document.write(reportHtml);
  win.document.close();
}

function setLoading(isLoading, label = '') {
  refs.uploadButton.disabled = isLoading;
  refs.demoButton.disabled = isLoading;
  refs.uploadButton.textContent = isLoading ? 'Procesando...' : 'Subir archivo';
  refs.demoButton.textContent = isLoading ? label : 'Usar datos de ejemplo';
}

function showToast(message, type = 'success') {
  refs.toast.textContent = message;
  refs.toast.className = `toast show ${type}`;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => refs.toast.classList.remove('show'), 3200);
}

function scrollChat(behavior = 'smooth') {
  window.requestAnimationFrame(() => {
    refs.chatWindow.scrollTo({ top: refs.chatWindow.scrollHeight, behavior });
  });
}

function prettyHeader(key) {
  const normalized = String(key || '').toLowerCase();
  const special = {
    posicion: 'Posición',
    participacion_pct: 'Participación %',
    variacion_pct: 'Variación %',
    puntaje_riesgo: 'Puntaje de riesgo',
    nivel_riesgo: 'Nivel de riesgo',
    z_score: 'Z-score',
    palabra_clave: 'Palabra clave',
    conteo: 'Conteo',
    metrica_a: 'Métrica A',
    metrica_b: 'Métrica B',
  };
  if (special[normalized]) return special[normalized];
  return String(key || '').replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return 'n/a';
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return new Intl.NumberFormat('es-CO', { maximumFractionDigits: 2 }).format(number);
}

function formatCell(value, key = '') {
  if (value === null || value === undefined) return '';
  const keyText = String(key).toLowerCase();
  if (typeof value === 'number') {
    const formatted = formatNumber(value);
    return keyText.includes('pct') || keyText.includes('participacion') || keyText.includes('porcentaje') ? `${formatted}%` : formatted;
  }
  return String(value);
}

function truncate(value, maxLength) {
  const text = String(value || '');
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('`', '&#096;');
}
