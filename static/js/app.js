// ── State ──
let projectId = null;
let pollTimer = null;
let gridSize = 4;

// ── DOM refs ──
const videoInput = document.getElementById('video-input');
const charInput = document.getElementById('char-input');
const videoDrop = document.getElementById('video-drop');
const charDrop = document.getElementById('char-drop');
const startBtn = document.getElementById('start-btn');
const cancelBtn = document.getElementById('cancel-btn');
const pauseBtn = document.getElementById('pause-btn');
const resumeBtn = document.getElementById('resume-btn');
const workspace = document.getElementById('workspace');

// ── Helpers for safe DOM building ──
function el(tag, attrs, children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'className') e.className = v;
      else if (k === 'textContent') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
  }
  if (children) {
    for (const c of Array.isArray(children) ? children : [children]) {
      if (typeof c === 'string') e.appendChild(document.createTextNode(c));
      else if (c) e.appendChild(c);
    }
  }
  return e;
}

// ── Upload handling ──
function setupDrop(dropEl, inputEl, onFile) {
  dropEl.addEventListener('click', (e) => {
    if (e.target === inputEl || e.target.tagName === 'LABEL' || e.target.classList.contains('btn')) return;
    inputEl.click();
  });
  inputEl.addEventListener('change', () => {
    if (inputEl.files[0]) onFile(inputEl.files[0]);
  });
  dropEl.addEventListener('dragover', e => {
    e.preventDefault();
    dropEl.classList.add('dragover');
  });
  dropEl.addEventListener('dragleave', () => dropEl.classList.remove('dragover'));
  dropEl.addEventListener('drop', e => {
    e.preventDefault();
    dropEl.classList.remove('dragover');
    if (e.dataTransfer.files[0]) {
      inputEl.files = e.dataTransfer.files;
      onFile(e.dataTransfer.files[0]);
    }
  });
}

let videoFile = null;
let charFile = null;
let videoFromAsset = null;
let videoAssetFilename = null;
let charFromAsset = null;

setupDrop(videoDrop, videoInput, file => {
  videoFile = file;
  videoFromAsset = null;
  const preview = document.getElementById('video-preview');
  const thumb = document.getElementById('video-thumb');
  const name = document.getElementById('video-name');
  thumb.src = URL.createObjectURL(file);
  name.textContent = file.name;
  preview.classList.remove('hidden');
  checkReady();
});

setupDrop(charDrop, charInput, file => {
  charFile = file;
  charFromAsset = null;
  const preview = document.getElementById('char-preview');
  const thumb = document.getElementById('char-thumb');
  const name = document.getElementById('char-name');
  thumb.src = URL.createObjectURL(file);
  name.textContent = file.name;
  preview.classList.remove('hidden');
  checkReady();
});

function checkReady() {
  startBtn.disabled = !((videoFile || videoFromAsset) && (charFile || charFromAsset));
}

// ── Grid size selector ──
document.querySelectorAll('.grid-size-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.grid-size-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    gridSize = parseInt(btn.dataset.size);
  });
});

// ── Project list ──
async function loadProjects() {
  try {
    const resp = await fetch('/api/projects');
    const projects = await resp.json();
    const container = document.getElementById('project-list');
    container.textContent = '';

    if (!projects.length) {
      container.appendChild(el('p', { className: 'empty-hint', textContent: '暂无项目，点击"新建项目"开始' }));
      return;
    }

    for (const p of projects) {
      const stageLabel = getStageLabel(p.stage);
      const date = p.created_at ? new Date(p.created_at).toLocaleString('zh-CN') : '';
      const statusClass = p.stage === 'complete' ? 'status-done' :
                          p.stage === 'failed' ? 'status-failed' :
                          p.stage === 'paused' ? 'status-paused' : 'status-pending';

      const card = el('div', { className: 'project-card', 'data-pid': p.project_id }, [
        el('div', { className: 'project-info' }, [
          el('span', { className: 'project-name', textContent: p.name || p.project_id }),
          el('span', { className: 'project-date', textContent: date }),
        ]),
        el('div', { className: 'project-meta' }, [
          el('span', { className: 'project-status ' + statusClass, textContent: stageLabel }),
          p.output_ready ? el('span', { className: 'badge', textContent: '有结果' }) : null,
          el('span', { className: 'project-grid-size', textContent: '宫格:' + (p.grid_size || 4) }),
        ]),
        el('div', { className: 'project-actions' }, [
          el('button', { type: 'button', className: 'btn small outline', textContent: '打开', onclick: () => openProject(p.project_id) }),
          el('button', { type: 'button', className: 'btn small danger', textContent: '删除', onclick: () => deleteProject(p.project_id) }),
        ]),
      ]);
      container.appendChild(card);
    }
  } catch (err) {
    console.error('Failed to load projects:', err);
  }
}

function getStageLabel(stage) {
  const labels = {
    idle: '待处理', analyzing: '分析中', extracting: '提取中',
    composing_grids: '合成中', generating_3view: '三视图', redrawing_grids: '重绘中',
    splitting_grids: '拆分中', assembling_video: '合成视频', complete: '已完成', failed: '失败', paused: '已暂停',
  };
  return labels[stage] || stage;
}

document.getElementById('new-project-btn').addEventListener('click', () => {
  resetWorkspace();
  workspace.classList.remove('hidden');
  projectId = null;
  videoFile = null;
  charFile = null;
  videoFromAsset = null;
  videoAssetFilename = null;
  charFromAsset = null;
  document.getElementById('video-preview').classList.add('hidden');
  document.getElementById('char-preview').classList.add('hidden');
  startBtn.disabled = true;
  startBtn.textContent = '开始处理';
});

async function openProject(pid) {
  projectId = pid;
  resetWorkspace();
  workspace.classList.remove('hidden');

  try {
    const resp = await fetch('/api/project/' + pid);
    const info = await resp.json();

    gridSize = info.grid_size || 4;
    document.querySelectorAll('.grid-size-btn').forEach(b => {
      b.classList.toggle('active', parseInt(b.dataset.size) === gridSize);
    });

    if (info.has_video) {
      videoFromAsset = info.video_asset_id;
      document.getElementById('video-thumb').src = '/api/project-input/' + pid + '/video';
      document.getElementById('video-name').textContent = info.video_filename || '(已上传)';
      document.getElementById('video-preview').classList.remove('hidden');
    }
    if (info.has_character) {
      charFromAsset = info.character_asset_id;
      document.getElementById('char-thumb').src = '/api/project-input/' + pid + '/character';
      document.getElementById('char-name').textContent = info.character_filename || '(已上传)';
      document.getElementById('char-preview').classList.remove('hidden');
    }

    if (info.video_info) showVideoInfo(info.video_info);

    showThreeview();

    if (info.stage === 'complete') {
      startBtn.textContent = '重新处理';
      startBtn.disabled = false;
      showResult();
      if (info.grids && info.grids.length) showGrids(info.grids, info.grids_dirty, false);
    } else if (info.stage === 'failed') {
      startBtn.textContent = '重新开始';
      startBtn.disabled = !(info.has_video && info.has_character);
    } else if (info.stage === 'paused') {
      document.getElementById('progress-section').classList.remove('hidden');
      resumeBtn.classList.remove('hidden');
      cancelBtn.classList.add('hidden');
      pauseBtn.classList.add('hidden');
      startBtn.textContent = '已暂停';
      startBtn.disabled = true;
      if (info.grids && info.grids.length) showGrids(info.grids, info.grids_dirty, false);
    } else if (info.stage !== 'idle') {
      document.getElementById('progress-section').classList.remove('hidden');
      cancelBtn.classList.remove('hidden');
      pauseBtn.classList.remove('hidden');
      resumeBtn.classList.add('hidden');
      startBtn.textContent = '处理中...';
      startBtn.disabled = true;
      pollTimer = setInterval(pollStatus, 2000);
      pollStatus();
    } else {
      checkReady();
    }
  } catch (err) {
    console.error('Failed to open project:', err);
  }
}

async function deleteProject(pid) {
  if (!confirm('确定删除此项目？')) return;
  await fetch('/api/project/' + pid, { method: 'DELETE' });
  if (projectId === pid) {
    projectId = null;
    workspace.classList.add('hidden');
  }
  loadProjects();
}

function resetWorkspace() {
  _prevGridStates = [];
  document.getElementById('grids-container').textContent = '';
  document.getElementById('analysis-section').classList.add('hidden');
  document.getElementById('progress-section').classList.add('hidden');
  document.getElementById('grids-section').classList.add('hidden');
  document.getElementById('result-section').classList.add('hidden');
  document.getElementById('threeview-section').classList.add('hidden');
  cancelBtn.classList.add('hidden');
  pauseBtn.classList.add('hidden');
  resumeBtn.classList.add('hidden');
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (rerollPollTimer) { clearInterval(rerollPollTimer); rerollPollTimer = null; }
}

// ── Start pipeline ──
startBtn.addEventListener('click', async () => {
  startBtn.disabled = true;
  startBtn.textContent = '上传中...';

  try {
    if (!projectId) {
      const createResp = await fetch('/api/project/create', { method: 'POST' });
      const createData = await createResp.json();
      projectId = createData.project_id;
    }

    if (videoFile) {
      const vForm = new FormData();
      vForm.append('file', videoFile);
      const vResp = await fetch('/api/upload/video?project_id=' + projectId, { method: 'POST', body: vForm });
      const vData = await vResp.json();
      // Auto-name project from video filename
      const vName = videoFile.name.replace(/\.[^.]+$/, '');
      if (vName) {
        await fetch('/api/project/' + projectId + '?name=' + encodeURIComponent(vName), { method: 'PUT' });
      }
    } else if (videoFromAsset) {
      await fetch('/api/project/' + projectId + '/use-asset?asset_type=video&asset_id=' + videoFromAsset, { method: 'POST' });
      // Auto-name project from asset filename
      const aName = (videoAssetFilename || '').replace(/\.[^.]+$/, '');
      if (aName) {
        await fetch('/api/project/' + projectId + '?name=' + encodeURIComponent(aName), { method: 'PUT' });
      }
    }

    if (charFile) {
      const cForm = new FormData();
      cForm.append('file', charFile);
      await fetch('/api/upload/character?project_id=' + projectId, { method: 'POST', body: cForm });
    } else if (charFromAsset) {
      await fetch('/api/project/' + projectId + '/use-asset?asset_type=character&asset_id=' + charFromAsset, { method: 'POST' });
    }

    await fetch('/api/pipeline/start?project_id=' + projectId + '&grid_size=' + gridSize, { method: 'POST' });

    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('grids-section').classList.add('hidden');
    document.getElementById('result-section').classList.add('hidden');
    cancelBtn.classList.remove('hidden');
    pauseBtn.classList.remove('hidden');
    resumeBtn.classList.add('hidden');
    startBtn.textContent = '处理中...';

    loadProjects();

    pollTimer = setInterval(pollStatus, 2000);
    pollStatus();

  } catch (err) {
    alert('上传失败: ' + err.message);
    startBtn.disabled = false;
    startBtn.textContent = '开始处理';
  }
});

// ── Cancel ──
cancelBtn.addEventListener('click', async () => {
  if (!projectId) return;
  await fetch('/api/pipeline/' + projectId + '/cancel', { method: 'POST' });
  cancelBtn.classList.add('hidden');
  if (pollTimer) clearInterval(pollTimer);
});

// ── Pause ──
pauseBtn.addEventListener('click', async () => {
  if (!projectId) return;
  await fetch('/api/pipeline/' + projectId + '/pause', { method: 'POST' });
  pauseBtn.classList.add('hidden');
  resumeBtn.classList.remove('hidden');
  cancelBtn.classList.add('hidden');
  startBtn.textContent = '已暂停';
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
});

// ── Resume ──
resumeBtn.addEventListener('click', async () => {
  if (!projectId) return;
  try {
    await fetch('/api/pipeline/' + projectId + '/resume', { method: 'POST' });
    resumeBtn.classList.add('hidden');
    pauseBtn.classList.remove('hidden');
    cancelBtn.classList.remove('hidden');
    startBtn.textContent = '处理中...';
    startBtn.disabled = true;
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 2000);
    pollStatus();
  } catch (err) {
    alert('恢复失败: ' + err.message);
  }
});

// ── Three-view display ──
function showThreeview() {
  if (!projectId) return;
  const section = document.getElementById('threeview-section');
  const img = document.getElementById('threeview-img');
  const url = '/api/files/' + projectId + '/cha_3view/threeview.png';
  // Test if image exists by loading it
  const testImg = new Image();
  testImg.onload = () => {
    img.src = url;
    section.classList.remove('hidden');
  };
  testImg.onerror = () => {
    section.classList.add('hidden');
  };
  testImg.src = url + '?t=' + Date.now();
}

// ── Stage order for stepper ──
const stageOrder = [
  'analyzing', 'extracting', 'composing_grids', 'generating_3view',
  'redrawing_grids', 'splitting_grids', 'assembling_video', 'complete',
];

async function pollStatus() {
  if (!projectId) return;

  try {
    const resp = await fetch('/api/pipeline/' + projectId + '/status');
    const data = await resp.json();

    const bar = document.getElementById('progress-bar');
    const text = document.getElementById('progress-text');
    const elapsed = document.getElementById('elapsed-time');

    bar.style.width = data.progress + '%';
    text.textContent = data.message || data.stage;

    if (data.elapsed_seconds > 0) {
      const mins = Math.floor(data.elapsed_seconds / 60);
      const secs = Math.floor(data.elapsed_seconds % 60);
      elapsed.textContent = '已用时: ' + mins + '分' + secs + '秒';
    }

    const currentIdx = stageOrder.indexOf(data.stage);
    document.querySelectorAll('.step').forEach(elNode => {
      const stage = elNode.dataset.stage;
      const idx = stageOrder.indexOf(stage);
      elNode.classList.remove('active', 'done', 'failed');
      if (data.stage === 'failed') {
        if (idx <= currentIdx) elNode.classList.add('failed');
      } else if (idx < currentIdx) {
        elNode.classList.add('done');
      } else if (idx === currentIdx) {
        elNode.classList.add('active');
      }
    });

    if (data.video_info) showVideoInfo(data.video_info);
    if (data.grids && data.grids.length) showGrids(data.grids, data.grids_dirty, data.rerolling);

    // Show three-view once generating_3view stage is done or later
    const tvStages = ['redrawing_grids', 'splitting_grids', 'assembling_video', 'complete'];
    if (tvStages.includes(data.stage)) showThreeview();

    if (data.stage === 'complete') {
      clearInterval(pollTimer);
      pollTimer = null;
      cancelBtn.classList.add('hidden');
      pauseBtn.classList.add('hidden');
      resumeBtn.classList.add('hidden');
      startBtn.textContent = '重新处理';
      startBtn.disabled = false;
      showResult();
      loadProjects();
    } else if (data.stage === 'failed') {
      clearInterval(pollTimer);
      pollTimer = null;
      cancelBtn.classList.add('hidden');
      pauseBtn.classList.add('hidden');
      resumeBtn.classList.add('hidden');
      startBtn.disabled = false;
      startBtn.textContent = '重新开始';
      loadProjects();
    } else if (data.stage === 'paused') {
      clearInterval(pollTimer);
      pollTimer = null;
      cancelBtn.classList.add('hidden');
      pauseBtn.classList.add('hidden');
      resumeBtn.classList.remove('hidden');
      startBtn.textContent = '已暂停';
      startBtn.disabled = true;
      loadProjects();
    }

  } catch (err) {
    console.error('Poll error:', err);
  }
}

function showVideoInfo(info) {
  const section = document.getElementById('analysis-section');
  section.classList.remove('hidden');

  document.getElementById('info-resolution').textContent = info.width + 'x' + info.height;
  document.getElementById('info-fps').textContent = info.fps + ' fps';
  document.getElementById('info-duration').textContent = info.duration.toFixed(2) + 's';
  document.getElementById('info-total-frames').textContent = info.total_frames;
  document.getElementById('info-unique-frames').textContent = info.unique_frames;
  document.getElementById('info-grids').textContent = info.grid_count;
  document.getElementById('info-pattern').textContent = info.hold_pattern || '-';
}

function showResult() {
  const section = document.getElementById('result-section');
  section.classList.remove('hidden');

  const video = document.getElementById('result-video');
  const dlBtn = document.getElementById('download-btn');
  const url = '/api/files/' + projectId + '/output/final.mp4';
  const cacheBust = url + '?t=' + Date.now();

  video.src = cacheBust;
  dlBtn.href = url;
  dlBtn.download = 'ai_redraw_output.mp4';
}

// ── Grid preview with re-roll ──
let rerollPollTimer = null;

// Track previous grid states to avoid unnecessary re-renders
let _prevGridStates = [];

function _gridStateKey(g) {
  return g.status + '|' + g.retry_count + '|' + g.error_msg + '|' + g.active_version + '|' + (g.versions || []).length;
}

function _buildGridItem(g, i) {
  const redrawnSrc = '/api/files/' + projectId + '/grids_redrawn/' + g.grid_name;
  const originalSrc = '/api/files/' + projectId + '/grids/' + g.grid_name;
  const statusClass = g.status === 'success' ? 'grid-success' :
                      g.status === 'failed' ? 'grid-failed' :
                      g.status === 'retrying' ? 'grid-retrying' : 'grid-pending';
  // Only cache-bust when we know it changed (on build, not every poll)
  const imgSrc = g.status === 'success' ? redrawnSrc + '?t=' + Date.now() : originalSrc;

  const img = el('img', { src: imgSrc, alt: 'Grid ' + (i + 1), loading: 'lazy' });
  const label = el('span', { className: 'grid-label', textContent: '#' + (i + 1) });
  const toggleHint = el('span', { className: 'grid-toggle-hint', textContent: '重绘' });
  const rerollBtn = el('button', {
    type: 'button',
    className: 'btn small reroll-btn',
    textContent: g.status === 'pending' || g.status === 'retrying' ? '生成中...' : '重新生成',
    onclick: (e) => { e.stopPropagation(); rerollGrid(i); },
  });
  if (g.status === 'pending' || g.status === 'retrying') rerollBtn.disabled = true;

  const overlay = el('div', { className: 'grid-overlay' }, [label, toggleHint, rerollBtn]);
  const item = el('div', { className: 'grid-item ' + statusClass }, [img, overlay]);

  // Status overlay for pending/retrying
  if (g.status === 'pending' || g.status === 'retrying') {
    const statusText = g.status === 'retrying'
      ? '重试中 (' + (g.retry_count || 1) + ')'
      : '生成中...';
    const statusOverlay = el('div', { className: 'grid-status-overlay' }, [
      el('div', { className: 'grid-status-spinner' }),
      el('span', { className: 'grid-status-text', textContent: statusText }),
    ]);
    item.appendChild(statusOverlay);
  }

  // Error message for failed grids
  if (g.status === 'failed' && g.error_msg) {
    const errBar = el('div', { className: 'grid-status-result failed',
      textContent: '失败: ' + g.error_msg.substring(0, 40) });
    item.appendChild(errBar);
  }

  // History button (if versions exist)
  const versions = g.versions || [];
  if (versions.length > 0) {
    const histBtn = el('button', {
      type: 'button',
      className: 'grid-history-btn',
      onclick: (e) => { e.stopPropagation(); toggleHistoryPopover(item, g, i); },
    }, [
      document.createTextNode('V'),
      el('span', { className: 'grid-history-badge', textContent: '' + versions.length }),
    ]);
    item.appendChild(histBtn);
  }

  // Click to toggle original/redrawn for successful grids
  if (g.status === 'success') {
    let showingRedrawn = true;
    item.style.cursor = 'pointer';
    item.addEventListener('click', () => {
      showingRedrawn = !showingRedrawn;
      img.src = showingRedrawn ? redrawnSrc + '?t=' + Date.now() : originalSrc;
      toggleHint.textContent = showingRedrawn ? '重绘' : '原图';
      item.classList.toggle('grid-showing-original', !showingRedrawn);
    });
  }

  return item;
}

function showGrids(grids, gridsDirty, rerolling) {
  const section = document.getElementById('grids-section');
  section.classList.remove('hidden');
  const container = document.getElementById('grids-container');

  // First render: build all items
  if (container.children.length !== grids.length) {
    container.textContent = '';
    _prevGridStates = [];
    for (let i = 0; i < grids.length; i++) {
      container.appendChild(_buildGridItem(grids[i], i));
      _prevGridStates.push(_gridStateKey(grids[i]));
    }
  } else {
    // Incremental update: only replace items whose state changed
    for (let i = 0; i < grids.length; i++) {
      const newKey = _gridStateKey(grids[i]);
      if (_prevGridStates[i] !== newKey) {
        const newItem = _buildGridItem(grids[i], i);
        container.replaceChild(newItem, container.children[i]);
        _prevGridStates[i] = newKey;
      }
    }
  }

  // Update video button in result section
  updateReassembleBtn(gridsDirty, rerolling);
}

function toggleHistoryPopover(itemEl, gridData, gridIndex) {
  // Close any existing popover
  const existing = itemEl.querySelector('.grid-history-popover');
  if (existing) { existing.remove(); return; }

  // Close other popovers
  document.querySelectorAll('.grid-history-popover').forEach(p => p.remove());

  const versions = gridData.versions || [];
  if (!versions.length) return;

  const popover = el('div', { className: 'grid-history-popover', onclick: (e) => e.stopPropagation() });
  popover.appendChild(el('h4', { textContent: '历史版本' }));

  for (const v of versions.slice().reverse()) {
    const isActive = gridData.active_version === v.version;
    const isFailed = v.status === 'failed';
    const cls = 'history-item' + (isActive ? ' active' : '') + (isFailed ? ' history-item-failed' : '');

    const thumb = isFailed
      ? el('div', { className: 'asset-icon', textContent: '✗', style: 'font-size:1.2rem;color:#e74c3c;width:36px;text-align:center;' })
      : el('img', { src: '/api/files/' + projectId + '/grids_redrawn/' + v.filename + '?t=' + Date.now(), alt: '' });

    const dateStr = v.created_at ? new Date(v.created_at).toLocaleString('zh-CN') : '';
    const info = el('div', { className: 'history-item-info' }, [
      el('span', { className: 'history-item-label', textContent: 'v' + v.version + (isActive ? ' (当前)' : '') + (isFailed ? ' 失败' : '') }),
      el('span', { className: 'history-item-date', textContent: dateStr }),
    ]);

    const row = el('div', { className: cls }, [thumb, info]);
    if (!isFailed && !isActive) {
      row.addEventListener('click', () => restoreGridVersion(gridIndex, v.version));
    }
    popover.appendChild(row);
  }

  itemEl.appendChild(popover);

  // Close on outside click
  const closeHandler = (e) => {
    if (!popover.contains(e.target) && !e.target.closest('.grid-history-btn')) {
      popover.remove();
      document.removeEventListener('click', closeHandler);
    }
  };
  setTimeout(() => document.addEventListener('click', closeHandler), 0);
}

async function restoreGridVersion(gridIndex, version) {
  if (!projectId) return;
  try {
    const resp = await fetch('/api/pipeline/' + projectId + '/grid/' + gridIndex + '/restore?version=' + version, { method: 'POST' });
    if (!resp.ok) { const d = await resp.json(); alert(d.detail || '恢复失败'); return; }
    // Close popovers and refresh
    document.querySelectorAll('.grid-history-popover').forEach(p => p.remove());
    pollRerollStatus();
  } catch (err) {
    alert('恢复失败: ' + err.message);
  }
}

function updateReassembleBtn(dirty, rerolling) {
  const btn = document.getElementById('reassemble-btn');
  if (!btn) return;
  // Only show when result section is visible
  const resultVisible = !document.getElementById('result-section').classList.contains('hidden');
  if (!resultVisible) { btn.classList.add('hidden'); return; }

  if (dirty && !rerolling) {
    btn.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = '更新视频';
  } else if (rerolling) {
    btn.classList.remove('hidden');
    btn.disabled = true;
    btn.textContent = '等待重绘完成...';
  } else {
    btn.classList.add('hidden');
  }
}

async function rerollGrid(gridIndex) {
  if (!projectId) return;

  try {
    await fetch('/api/pipeline/' + projectId + '/reroll?grid_index=' + gridIndex, { method: 'POST' });

    // Start polling for grid updates if not already
    if (!rerollPollTimer) {
      rerollPollTimer = setInterval(pollRerollStatus, 2000);
      pollRerollStatus();
    }
  } catch (err) {
    alert('重新生成失败: ' + err.message);
  }
}

async function pollRerollStatus() {
  if (!projectId) return;
  try {
    const resp = await fetch('/api/pipeline/' + projectId + '/status');
    const data = await resp.json();

    if (data.grids && data.grids.length) {
      showGrids(data.grids, data.grids_dirty, data.rerolling);
    }

    // Stop polling when no more rerolls active
    if (!data.rerolling) {
      clearInterval(rerollPollTimer);
      rerollPollTimer = null;
    }
  } catch (err) {
    console.error('Reroll poll error:', err);
  }
}

async function reassembleVideo() {
  if (!projectId) return;
  const btn = document.getElementById('reassemble-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '合成中...';
  }

  try {
    await fetch('/api/pipeline/' + projectId + '/reassemble', { method: 'POST' });

    // Show progress and poll
    document.getElementById('progress-section').classList.remove('hidden');
    cancelBtn.classList.add('hidden');
    pauseBtn.classList.add('hidden');
    resumeBtn.classList.add('hidden');
    startBtn.disabled = true;
    startBtn.textContent = '合成中...';

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 2000);
    pollStatus();
  } catch (err) {
    alert('合成失败: ' + err.message);
    if (btn) {
      btn.disabled = false;
      btn.textContent = '更新视频';
    }
  }
}

// ── Asset picker modal ──
const assetModal = document.getElementById('asset-modal');
let assetPickCallback = null;

document.getElementById('asset-modal-close').addEventListener('click', () => {
  assetModal.classList.add('hidden');
});

document.getElementById('pick-video-asset').addEventListener('click', () => {
  showAssetPicker('video', (asset) => {
    videoFromAsset = asset.asset_id;
    videoAssetFilename = asset.filename;
    videoFile = null;
    document.getElementById('video-thumb').src = '/api/asset-file/video/' + asset.asset_id + '/original';
    document.getElementById('video-name').textContent = asset.filename;
    document.getElementById('video-preview').classList.remove('hidden');
    checkReady();
  });
});

document.getElementById('pick-char-asset').addEventListener('click', () => {
  showAssetPicker('character', (asset) => {
    charFromAsset = asset.asset_id;
    charFile = null;
    document.getElementById('char-thumb').src = asset.thumbnail
      ? '/api/asset-file/character/' + asset.asset_id + '/thumb.png'
      : '/api/asset-file/character/' + asset.asset_id + '/original';
    document.getElementById('char-name').textContent = asset.filename;
    document.getElementById('char-preview').classList.remove('hidden');
    checkReady();
  });
});

async function showAssetPicker(assetType, onPick) {
  assetPickCallback = onPick;
  document.getElementById('asset-modal-title').textContent =
    assetType === 'video' ? '选择视频素材' : '选择角色素材';

  const resp = await fetch('/api/assets/' + assetType);
  const assets = await resp.json();
  const body = document.getElementById('asset-modal-body');
  body.textContent = '';

  if (!assets.length) {
    body.appendChild(el('p', { className: 'empty-hint', textContent: '暂无素材' }));
  } else {
    for (const a of assets) {
      const thumbEl = a.thumbnail
        ? el('img', { src: '/api/asset-file/' + assetType + '/' + a.asset_id + '/thumb.png', alt: '' })
        : el('div', { className: 'asset-icon', textContent: assetType === 'video' ? '🎬' : '🎨' });
      const nameEl = el('span', { className: 'asset-name', textContent: a.filename });
      const dateEl = el('span', { className: 'asset-date', textContent: a.created_at ? new Date(a.created_at).toLocaleDateString('zh-CN') : '' });

      const card = el('div', { className: 'asset-card', onclick: () => {
        assetModal.classList.add('hidden');
        if (assetPickCallback) assetPickCallback(a);
      }}, [thumbEl, nameEl, dateEl]);
      body.appendChild(card);
    }
  }

  assetModal.classList.remove('hidden');
}

// ── Init ──
loadProjects();
