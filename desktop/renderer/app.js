const state = {
  agentUrl: null,
  jobs: [],
  selectedJobId: null,
};

const els = {
  agentStatus: document.getElementById("agent-status"),
  nodeForm: document.getElementById("node-form"),
  stopNodeBtn: document.getElementById("stop-node"),
  shareForm: document.getElementById("share-form"),
  downloadForm: document.getElementById("download-form"),
  queueList: document.getElementById("queue-list"),
  chunkSummary: document.getElementById("chunk-summary"),
  chunkGrid: document.getElementById("chunk-grid"),
  swarmMeta: document.getElementById("swarm-meta"),
  swarmTable: document.getElementById("swarm-table"),
  activityLog: document.getElementById("activity-log"),
  browseShareBtn: document.getElementById("browse-share"),
  browseTargetBtn: document.getElementById("browse-target"),
  shareFileInput: document.getElementById("share-file"),
  downloadTargetInput: document.getElementById("download-target"),
  downloadInfoHashInput: document.getElementById("download-info-hash"),
};

function logActivity(message) {
  const line = document.createElement("div");
  line.className = "log-line";
  line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  els.activityLog.prepend(line);
}

async function api(path, options = {}) {
  const response = await fetch(`${state.agentUrl}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || {};
    const message = detail.message || `Request failed (${response.status})`;
    throw new Error(message);
  }

  return payload;
}

function renderJobs() {
  els.queueList.innerHTML = "";

  if (state.jobs.length === 0) {
    els.queueList.innerHTML = '<div class="mono muted">No download jobs queued.</div>';
    return;
  }

  for (const job of state.jobs) {
    const completed = job.progress ? job.progress.completed_chunks.length : 0;
    const total = job.progress ? job.progress.total_chunks : 0;
    const ratio = total === 0 ? 0 : Math.round((completed / total) * 100);

    const item = document.createElement("button");
    item.type = "button";
    item.className = `queue-item ${job.status} ${state.selectedJobId === job.job_id ? "active" : ""}`;
    item.innerHTML = `
      <div class="queue-head">
        <strong>${job.status.toUpperCase()}</strong>
        <span class="queue-hash">${job.info_hash.slice(0, 16)}...</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" style="width:${ratio}%;"></div>
      </div>
      <div class="mono muted">${completed}/${total} chunks · ${ratio}%</div>
    `;

    item.addEventListener("click", () => {
      state.selectedJobId = job.job_id;
      renderJobs();
      renderChunkMap();
      refreshSwarmForSelected();
    });

    els.queueList.append(item);
  }
}

function renderChunkMap() {
  els.chunkGrid.innerHTML = "";

  const selected = state.jobs.find((job) => job.job_id === state.selectedJobId);
  if (!selected || !selected.progress) {
    els.chunkSummary.textContent = "Select a running/completed job to inspect chunks.";
    return;
  }

  const progress = selected.progress;
  const completedSet = new Set(progress.completed_chunks);
  els.chunkSummary.textContent = `${progress.completed_chunks.length}/${progress.total_chunks} chunks complete`;

  for (let index = 0; index < progress.total_chunks; index += 1) {
    const cell = document.createElement("div");
    cell.className = `chunk ${completedSet.has(index) ? "completed" : "pending"}`;
    cell.title = `Chunk ${index}`;
    els.chunkGrid.append(cell);
  }
}

function renderSwarm(swarm) {
  els.swarmTable.innerHTML = "";
  if (!swarm) {
    els.swarmMeta.textContent = "No info hash selected.";
    return;
  }

  els.swarmMeta.textContent = `Swarm size ${swarm.swarm_size} · Seeds ${swarm.seed_count} · Chunks ${swarm.total_chunks}`;

  for (const peer of swarm.peers) {
    const row = document.createElement("div");
    row.className = "swarm-row mono";
    row.innerHTML = `
      <div>${peer.peer_id}</div>
      <div>${peer.host}:${peer.port}</div>
      <div>${peer.available_chunks.length} chunks</div>
    `;
    els.swarmTable.append(row);
  }
}

async function refreshNodeInfo() {
  try {
    const nodeInfo = await api("/api/v1/node");
    if (nodeInfo.running) {
      els.agentStatus.textContent = `Node: ${nodeInfo.peer_id} (${nodeInfo.host}:${nodeInfo.port})`;
    } else {
      els.agentStatus.textContent = "Node: stopped";
    }
  } catch (error) {
    els.agentStatus.textContent = "Agent: unavailable";
  }
}

async function refreshJobs() {
  try {
    const payload = await api("/api/v1/downloads");
    state.jobs = payload.jobs || [];

    if (!state.selectedJobId && state.jobs.length > 0) {
      state.selectedJobId = state.jobs[0].job_id;
    }

    renderJobs();
    renderChunkMap();
  } catch (error) {
    logActivity(`Failed to refresh jobs: ${error.message}`);
  }
}

async function refreshSwarmForSelected() {
  const selected = state.jobs.find((job) => job.job_id === state.selectedJobId);
  if (!selected) {
    renderSwarm(null);
    return;
  }

  try {
    const swarm = await api(`/api/v1/swarm/${selected.info_hash}`);
    renderSwarm(swarm);
  } catch (error) {
    renderSwarm(null);
    logActivity(`Swarm lookup failed: ${error.message}`);
  }
}

els.nodeForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const body = {
    peer_id: document.getElementById("peer-id").value || null,
    host: document.getElementById("host").value,
    port: Number(document.getElementById("port").value),
    data_dir: document.getElementById("data-dir").value,
    tracker_url: document.getElementById("tracker-url").value,
  };

  try {
    const response = await api("/api/v1/node/start", {
      method: "POST",
      body: JSON.stringify(body),
    });
    logActivity(`Node started as ${response.peer_id} on ${response.host}:${response.port}`);
    await refreshNodeInfo();
  } catch (error) {
    logActivity(`Node start failed: ${error.message}`);
  }
});

els.stopNodeBtn.addEventListener("click", async () => {
  try {
    await api("/api/v1/node/stop", { method: "POST" });
    logActivity("Node stopped.");
    await refreshNodeInfo();
  } catch (error) {
    logActivity(`Node stop failed: ${error.message}`);
  }
});

els.browseShareBtn.addEventListener("click", async () => {
  const filePath = await window.desktopBridge.pickShareFile();
  if (filePath) {
    els.shareFileInput.value = filePath;
  }
});

els.browseTargetBtn.addEventListener("click", async () => {
  const defaultName = "download.bin";
  const filePath = await window.desktopBridge.pickDownloadTarget(defaultName);
  if (filePath) {
    els.downloadTargetInput.value = filePath;
  }
});

els.shareForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    file_path: els.shareFileInput.value,
    chunk_size_bytes: Number(document.getElementById("share-chunk-size").value),
  };

  try {
    const shared = await api("/api/v1/share", {
      method: "POST",
      body: JSON.stringify(body),
    });
    els.downloadInfoHashInput.value = shared.info_hash;
    logActivity(`Shared ${shared.file_name} (${shared.info_hash})`);
  } catch (error) {
    logActivity(`Share failed: ${error.message}`);
  }
});

els.downloadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    info_hash: els.downloadInfoHashInput.value,
    target_path: els.downloadTargetInput.value,
  };

  try {
    const job = await api("/api/v1/downloads", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.selectedJobId = job.job_id;
    logActivity(`Queued download ${job.job_id.slice(0, 8)} for ${job.info_hash.slice(0, 10)}...`);
    await refreshJobs();
    await refreshSwarmForSelected();
  } catch (error) {
    logActivity(`Download queue failed: ${error.message}`);
  }
});

async function bootstrap() {
  state.agentUrl = await window.desktopBridge.getAgentUrl();
  logActivity(`Agent URL: ${state.agentUrl}`);

  await refreshNodeInfo();
  await refreshJobs();

  setInterval(async () => {
    await refreshNodeInfo();
    await refreshJobs();
    await refreshSwarmForSelected();
  }, 1000);
}

bootstrap();
