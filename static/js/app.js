// State
let projectId = null;
let pollTimer = null;

// DOM refs
const videoInput = document.getElementById('video-input');
const charInput = document.getElementById('char-input');
const videoDrop = document.getElementById('video-drop');
const charDrop = document.getElementById('char-drop');
const startBtn = document.getElementById('start-btn');
const cancelBtn = document.getElementById('cancel-btn');

// Upload handling
function setupDrop(dropEl, inputEl, onFile) {
  dropEl.addEventListener('click', (e) => {
    // Avoid double trigger when clicking the <label for="..."> which natively opens the file picker
    if (e.target === inputEl || e.target.tagName === 'LABEL') return;
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

setupDrop(videoDrop, videoInput, file => {
  videoFile = file;
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
  const preview = document.getElementById('char-preview');
  const thumb = document.getElementById('char-thumb');
  const name = document.getElementById('char-name');
  thumb.src = URL.createObjectURL(file);
  name.textContent = file.name;
  preview.classList.remove('hidden');
  checkReady();
});

function checkReady() {
  startBtn.disabled = !(videoFile && charFile);
}

// Start pipeline
startBtn.addEventListener('click', async () => {
  startBtn.disabled = true;
  startBtn.textContent = '上传中...';

  try {
    // Upload video
    const vForm = new FormData();
    vForm.append('file', videoFile);
    const vResp = await fetch('/api/upload/video', { method: 'POST', body: vForm });
    const vData = await vResp.json();
    projectId = vData.project_id;

    // Upload character
    const cForm = new FormData();
    cForm.append('file', charFile);
    const cResp = await fetch(`/api/upload/character?project_id=${projectId}`, {
      method: 'POST', body: cForm,
    });
    await cResp.json();

    // Start pipeline
    await fetch(`/api/pipeline/start?project_id=${projectId}`, { method: 'POST' });

    // Show progress UI
    document.getElementById('progress-section').classList.remove('hidden');
    cancelBtn.classList.remove('hidden');
    startBtn.textContent = '处理中...';

    // Start polling
    pollTimer = setInterval(pollStatus, 2000);
    pollStatus();

  } catch (err) {
    alert('上传失败: ' + err.message);
    startBtn.disabled = false;
    startBtn.textContent = '开始处理';
  }
});

// Cancel
cancelBtn.addEventListener('click', async () => {
  if (!projectId) return;
  await fetch(`/api/pipeline/${projectId}/cancel`, { method: 'POST' });
  cancelBtn.classList.add('hidden');
  if (pollTimer) clearInterval(pollTimer);
});

// Stage order for stepper
const stageOrder = [
  'analyzing', 'extracting', 'composing_grids', 'generating_3view',
  'redrawing_grids', 'splitting_grids', 'assembling_video', 'complete',
];

async function pollStatus() {
  if (!projectId) return;

  try {
    const resp = await fetch(`/api/pipeline/${projectId}/status`);
    const data = await resp.json();

    // Update progress bar
    const bar = document.getElementById('progress-bar');
    const text = document.getElementById('progress-text');
    const elapsed = document.getElementById('elapsed-time');

    bar.style.width = data.progress + '%';
    text.textContent = data.message || data.stage;

    if (data.elapsed_seconds > 0) {
      const mins = Math.floor(data.elapsed_seconds / 60);
      const secs = Math.floor(data.elapsed_seconds % 60);
      elapsed.textContent = `已用时: ${mins}分${secs}秒`;
    }

    // Update stepper
    const currentIdx = stageOrder.indexOf(data.stage);
    document.querySelectorAll('.step').forEach(el => {
      const stage = el.dataset.stage;
      const idx = stageOrder.indexOf(stage);
      el.classList.remove('active', 'done', 'failed');
      if (data.stage === 'failed') {
        if (idx <= currentIdx) el.classList.add('failed');
      } else if (idx < currentIdx) {
        el.classList.add('done');
      } else if (idx === currentIdx) {
        el.classList.add('active');
      }
    });

    // Update video info if available
    if (data.video_info) {
      showVideoInfo(data.video_info);
    }

    // Check terminal states
    if (data.stage === 'complete') {
      clearInterval(pollTimer);
      cancelBtn.classList.add('hidden');
      startBtn.textContent = '开始处理';
      showResult();
    } else if (data.stage === 'failed') {
      clearInterval(pollTimer);
      cancelBtn.classList.add('hidden');
      startBtn.disabled = false;
      startBtn.textContent = '重新开始';
    }

  } catch (err) {
    console.error('Poll error:', err);
  }
}

function showVideoInfo(info) {
  const section = document.getElementById('analysis-section');
  section.classList.remove('hidden');

  document.getElementById('info-resolution').textContent = `${info.width}x${info.height}`;
  document.getElementById('info-fps').textContent = `${info.fps} fps`;
  document.getElementById('info-duration').textContent = `${info.duration.toFixed(2)}s`;
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
  const url = `/api/files/${projectId}/output/final.mp4`;

  video.src = url;
  dlBtn.href = url;
  dlBtn.download = 'ai_redraw_output.mp4';
}
