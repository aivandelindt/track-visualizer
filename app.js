const DEFAULT_DATA_URL = "output/tracklist_analysis.json";
const ANALYZE_ENDPOINT = "/api/analyze";

const filters = [
  { id: "all", label: "All" },
  { id: "high-energy", label: "Energy 8+" },
  { id: "trancey", label: "128-145 BPM" },
  { id: "slow-burn", label: "Under 100 BPM" },
];

const compatibilityLabels = [
  { label: "Harmonic", className: "pill-good" },
  { label: "Energy", className: "pill-accent" },
  { label: "Tempo", className: "pill-warn" },
];

const state = {
  tracks: [],
  filteredTracks: [],
  selectedIndex: 0,
  filter: "all",
  search: "",
  chart: null,
  pendingFiles: [],
  source: {
    label: DEFAULT_DATA_URL,
    folder: "Bundled sample JSON",
    genre: "trance",
    fileCount: 0,
    mode: "sample",
  },
};

const elements = {};

document.addEventListener("DOMContentLoaded", initialize);

async function initialize() {
  cacheElements();
  renderCompatibilityLegend();
  renderFilters();
  attachEvents();
  await loadDefaultData();
}

function cacheElements() {
  const ids = [
    "summaryGrid",
    "selectedTitle",
    "selectedArtist",
    "selectedBadges",
    "selectedMetrics",
    "cueStrip",
    "trackCount",
    "searchInput",
    "filterRow",
    "trackList",
    "recommendations",
    "markerList",
    "markerCount",
    "compatibilityLegend",
    "energyChart",
    "folderInput",
    "genreSelect",
    "analyzeButton",
    "folderLabel",
    "analysisStatus",
  ];

  for (const id of ids) {
    elements[id] = document.getElementById(id);
  }
}

function attachEvents() {
  elements.searchInput.addEventListener("input", (event) => {
    state.search = event.target.value.trim().toLowerCase();
    applyFilters();
  });

  elements.folderInput.addEventListener("change", handleFolderSelection);
  elements.genreSelect.addEventListener("change", () => {
    if (state.pendingFiles.length > 0) {
      setAnalysisStatus(
        `Ready to analyze ${state.pendingFiles.length} files with the ${elements.genreSelect.value} preset.`,
        "idle",
      );
    }
  });
  elements.analyzeButton.addEventListener("click", handleAnalyzeClick);
}

async function loadDefaultData() {
  setFolderSelectionSummary("Bundled sample JSON", 0, true);
  setAnalysisStatus("Loading bundled analysis JSON...", "idle");

  try {
    const response = await fetch(DEFAULT_DATA_URL);
    if (!response.ok) {
      throw new Error(`Failed to load ${DEFAULT_DATA_URL}: ${response.status}`);
    }

    const tracks = await response.json();
    setTracks(tracks, {
      label: DEFAULT_DATA_URL,
      folder: "Bundled sample JSON",
      genre: elements.genreSelect.value,
      fileCount: tracks.length,
      mode: "sample",
    });
    setAnalysisStatus(
      `Loaded ${tracks.length} tracks from bundled JSON. Run server.py to analyze a selected folder.`,
      "success",
    );
  } catch (error) {
    renderError(error);
    setAnalysisStatus("Unable to load bundled JSON. Serve this folder over HTTP.", "error");
  }
}

function setTracks(tracks, source = {}) {
  state.tracks = tracks;
  state.filteredTracks = [...tracks];
  state.selectedIndex = 0;
  state.source = {
    ...state.source,
    ...source,
    fileCount: source.fileCount ?? tracks.length,
  };
  renderDashboard();
}

function handleFolderSelection(event) {
  state.pendingFiles = Array.from(event.target.files || []);
  const folderName = getFolderName(state.pendingFiles);
  const hasFiles = state.pendingFiles.length > 0;

  setFolderSelectionSummary(folderName, state.pendingFiles.length, !hasFiles);
  elements.analyzeButton.disabled = !hasFiles;

  if (!hasFiles) {
    setAnalysisStatus("Choose a folder of audio files to run a new analysis.", "idle");
    return;
  }

  setAnalysisStatus(
    `Ready to analyze ${state.pendingFiles.length} files with the ${elements.genreSelect.value} preset.`,
    "idle",
  );
}

async function handleAnalyzeClick() {
  if (state.pendingFiles.length === 0) {
    setAnalysisStatus("Choose a folder before starting analysis.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("genre", elements.genreSelect.value);
  for (const file of state.pendingFiles) {
    formData.append("tracks", file, file.webkitRelativePath || file.name);
  }

  elements.analyzeButton.disabled = true;
  elements.genreSelect.disabled = true;
  setAnalysisStatus(`Analyzing ${state.pendingFiles.length} audio files...`, "idle");

  try {
    const response = await fetch(ANALYZE_ENDPOINT, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }

    const payload = await response.json();
    setTracks(payload.tracks || [], {
      label: payload.source?.command || ANALYZE_ENDPOINT,
      folder: payload.source?.folder || getFolderName(state.pendingFiles),
      genre: payload.source?.genre || elements.genreSelect.value,
      fileCount: payload.source?.fileCount || state.pendingFiles.length,
      mode: "uploaded",
    });
    setAnalysisStatus(
      `Analyzed ${payload.source?.fileCount || state.pendingFiles.length} files from ${payload.source?.folder || getFolderName(state.pendingFiles)}.`,
      "success",
    );
  } catch (error) {
    setAnalysisStatus(
      `${error.message} Start the dashboard with python server.py if the analysis endpoint is unavailable.`,
      "error",
    );
  } finally {
    elements.analyzeButton.disabled = state.pendingFiles.length === 0;
    elements.genreSelect.disabled = false;
  }
}

async function readErrorMessage(response) {
  try {
    const payload = await response.json();
    return payload.error || `Request failed with status ${response.status}.`;
  } catch {
    return `Request failed with status ${response.status}.`;
  }
}

function getFolderName(files) {
  const firstFile = files[0];
  if (!firstFile) {
    return "Bundled sample JSON";
  }

  const relativePath = String(firstFile.webkitRelativePath || "");
  const [folderName] = relativePath.split("/");
  return folderName || "Selected folder";
}

function setFolderSelectionSummary(label, fileCount, isSample = false) {
  if (isSample) {
    elements.folderLabel.textContent = label;
    return;
  }

  const countLabel = `${fileCount} file${fileCount === 1 ? "" : "s"}`;
  elements.folderLabel.textContent = `${label} · ${countLabel}`;
}

function setAnalysisStatus(message, tone) {
  elements.analysisStatus.textContent = message;
  elements.analysisStatus.dataset.tone = tone;
}

function renderFilters() {
  elements.filterRow.innerHTML = filters
    .map(
      (filter) => `
        <button class="filter-btn ${filter.id === state.filter ? "is-active" : ""}" data-filter="${filter.id}">
          ${filter.label}
        </button>
      `,
    )
    .join("");

  elements.filterRow.querySelectorAll(".filter-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      renderFilters();
      applyFilters();
    });
  });
}

function renderCompatibilityLegend() {
  elements.compatibilityLegend.innerHTML = compatibilityLabels
    .map(
      (item) => `
        <span class="pill ${item.className}">${item.label}</span>
      `,
    )
    .join("");
}

function applyFilters() {
  state.filteredTracks = state.tracks.filter((track) => {
    const matchesSearch = !state.search || searchTrack(track, state.search);
    const matchesFilter = matchesPreset(track, state.filter);
    return matchesSearch && matchesFilter;
  });

  if (state.filteredTracks.length === 0) {
    state.selectedIndex = 0;
    renderEmptyState();
    return;
  }

  if (state.selectedIndex >= state.filteredTracks.length) {
    state.selectedIndex = 0;
  }

  renderDashboard();
}

function renderDashboard() {
  const selectedTrack = state.filteredTracks[state.selectedIndex];
  if (!selectedTrack) {
    renderEmptyState();
    return;
  }

  renderSummary();
  renderTrackList();
  renderSelectedTrack(selectedTrack);
  renderRecommendations(selectedTrack);
  renderMarkers(selectedTrack);
  renderChart(selectedTrack);
}

function renderSummary() {
  const tracks = state.tracks;
  const totalDuration = tracks.reduce((sum, track) => sum + Number(track.duration_sec || 0), 0);
  const averageBpm = average(tracks.map((track) => Number(track.bpm || 0)));
  const averageEnergy = average(tracks.map((track) => Number(track.avg_energy_level || 0)));
  const quickestDrop = Math.min(
    ...tracks.map((track) => firstDropTime(track)).filter((value) => Number.isFinite(value)),
  );

  const summaryItems = [
    {
      label: "Tracks",
      value: `${tracks.length}`,
      meta: state.source.mode === "uploaded" ? `${state.source.folder} · ${state.source.genre}` : "Bundled sample JSON",
    },
    { label: "Avg BPM", value: `${averageBpm.toFixed(1)}`, meta: "Across entire library" },
    { label: "Avg Energy", value: `${averageEnergy.toFixed(1)}/10`, meta: "Coarse mix intensity" },
    {
      label: "Fastest Drop",
      value: Number.isFinite(quickestDrop) ? `${quickestDrop.toFixed(1)}s` : "n/a",
      meta: "Earliest cue point",
    },
  ];

  elements.summaryGrid.innerHTML = summaryItems
    .map(
      (item) => `
        <div class="metric-card">
          <div class="metric-label">${item.label}</div>
          <div class="metric-value">${item.value}</div>
          <div class="metric-meta">${item.meta}</div>
        </div>
      `,
    )
    .join("");

  elements.trackCount.textContent = `${state.filteredTracks.length} of ${tracks.length} tracks`;
}

function renderTrackList() {
  elements.trackList.innerHTML = state.filteredTracks
    .map((track, index) => {
      const isActive = index === state.selectedIndex;
      const firstDrop = firstDropTime(track);
      const markers = track.structure_markers || [];
      return `
        <article class="track-card ${isActive ? "is-active" : ""}" data-index="${index}">
          <div class="track-topline">
            <div>
              <h3 class="track-name">${escapeHtml(track.title)}</h3>
              <p class="track-artist">${escapeHtml(track.artist)}</p>
            </div>
            <span class="track-chip">${track.camelot} · ${track.bpm.toFixed(1)} BPM</span>
          </div>
          <div class="track-tags">
            <span class="track-chip">Energy ${track.avg_energy_level}/10</span>
            <span class="track-chip">${track.duration_sec.toFixed(1)}s</span>
            <span class="track-chip">${markers.length} cues</span>
            <span class="track-chip">Drop ${Number.isFinite(firstDrop) ? `${firstDrop.toFixed(1)}s` : "n/a"}</span>
          </div>
        </article>
      `;
    })
    .join("");

  elements.trackList.querySelectorAll(".track-card").forEach((card) => {
    card.addEventListener("click", () => {
      state.selectedIndex = Number(card.dataset.index);
      renderDashboard();
    });
  });
}

function renderSelectedTrack(track) {
  elements.selectedTitle.textContent = track.title;
  elements.selectedArtist.textContent = track.artist;
  elements.selectedBadges.innerHTML = [
    `<span class="pill pill-accent">${track.camelot}</span>`,
    `<span class="pill pill-good">${track.key}</span>`,
    `<span class="pill pill-warn">${track.bpm.toFixed(1)} BPM</span>`,
  ].join("");

  const dropTime = firstDropTime(track);
  const peakCount = countMarkers(track, "peak_section");
  const buildCount = countMarkers(track, "build_up") + countMarkers(track, "build_down");
  const structureSpan = structureSpanText(track);
  const metrics = [
    { label: "Duration", value: `${track.duration_sec.toFixed(1)}s`, meta: "Track length" },
    { label: "Energy", value: `${track.avg_energy_level}/10`, meta: "Average intensity" },
    { label: "First drop", value: formatSeconds(dropTime), meta: "Primary transition cue" },
    { label: "Structure", value: `${track.structure_markers.length}`, meta: structureSpan },
    { label: "Peaks", value: `${peakCount}`, meta: `${buildCount} build segments` },
    { label: "Key", value: track.camelot, meta: track.key },
  ];

  elements.selectedMetrics.innerHTML = metrics
    .map(
      (item) => `
        <div class="stat-card">
          <div class="label">${item.label}</div>
          <div class="value">${item.value}</div>
          <div class="meta">${item.meta}</div>
        </div>
      `,
    )
    .join("");

  const cueCards = [
    {
      title: "Mix-in cue",
      value: formatSeconds(dropTime),
      note: "Start the next deck on the first drop or the lead-in before it.",
    },
    {
      title: "Peak window",
      value: peakWindow(track),
      note: "Best section for long blends or energy lock.",
    },
    {
      title: "Outro cue",
      value: outroCue(track),
      note: "Use the first sustained build-down to exit cleanly.",
    },
  ];

  elements.cueStrip.innerHTML = cueCards
    .map(
      (cue) => `
        <article class="cue-card">
          <strong>${cue.title}</strong>
          <span>${cue.value}</span>
          <div class="compat-note">${cue.note}</div>
        </article>
      `,
    )
    .join("");
}

function renderRecommendations(track) {
  const recommendations = state.tracks
    .filter((candidate) => candidate.file !== track.file)
    .map((candidate) => ({
      track: candidate,
      score: compatibilityScore(track, candidate),
    }))
    .sort((left, right) => right.score - left.score)
    .slice(0, 4);

  if (recommendations.length === 0) {
    elements.recommendations.innerHTML = '<div class="empty-state">No recommendations available.</div>';
    return;
  }

  elements.recommendations.innerHTML = recommendations
    .map(({ track: candidate, score }) => {
      const harmonics = harmonicNote(track, candidate);
      return `
        <article class="recommendation-card">
          <div class="recommendation-card-top">
            <div>
              <h3>${escapeHtml(candidate.title)}</h3>
              <p class="track-artist">${escapeHtml(candidate.artist)}</p>
            </div>
            <div class="score">${score.toFixed(0)}%</div>
          </div>
          <div class="recommendation-meta">
            ${candidate.camelot} · ${candidate.key} · ${candidate.bpm.toFixed(1)} BPM
            <br />
            ${harmonics}
          </div>
        </article>
      `;
    })
    .join("");
}

function renderMarkers(track) {
  const markers = [...(track.structure_markers || [])].sort((left, right) => Number(left.time) - Number(right.time));
  elements.markerCount.textContent = `${markers.length} markers`;

  elements.markerList.innerHTML = markers
    .map((marker) => {
      const label = marker.type.replace(/_/g, " ");
      return `
        <div class="marker-item">
          <div class="marker-type">${label}</div>
          <div class="marker-sub">${markerDescription(marker.type)}</div>
          <div class="marker-time">${formatSeconds(marker.time)}${marker.end_time ? ` - ${formatSeconds(marker.end_time)}` : ""}</div>
        </div>
      `;
    })
    .join("");
}

function renderChart(track) {
  const labels = (track.energy_levels || []).map((point) => point.time);
  const points = (track.energy_levels || []).map((point) => ({ x: point.time, y: point.level }));
  const markers = track.structure_markers || [];

  if (state.chart) {
    state.chart.destroy();
  }

  state.chart = new Chart(elements.energyChart, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Energy",
          data: points,
          borderColor: "rgba(242, 162, 58, 0.95)",
          backgroundColor: "rgba(242, 162, 58, 0.18)",
          fill: true,
          tension: 0.32,
          pointRadius: 3,
          pointHoverRadius: 5,
          pointBackgroundColor: "#ffd69a",
          pointBorderColor: "#0b0d10",
          pointBorderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: "index",
      },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          backgroundColor: "rgba(8, 10, 13, 0.96)",
          borderColor: "rgba(242, 162, 58, 0.35)",
          borderWidth: 1,
          titleColor: "#fff",
          bodyColor: "#dfe5ea",
          padding: 12,
          callbacks: {
            title(items) {
              return `Time ${formatSeconds(items[0].parsed.x)}`;
            },
            label(context) {
              return `Energy ${Number(context.parsed.y).toFixed(0)}/10`;
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          grid: {
            color: "rgba(255, 255, 255, 0.05)",
          },
          ticks: {
            color: "#8a95a2",
            callback(value) {
              return `${Number(value).toFixed(0)}s`;
            },
          },
          title: {
            display: true,
            text: "Time",
            color: "#9aa5b1",
          },
        },
        y: {
          min: 1,
          max: 10,
          grid: {
            color: "rgba(255, 255, 255, 0.05)",
          },
          ticks: {
            color: "#8a95a2",
            stepSize: 1,
          },
          title: {
            display: true,
            text: "Energy level",
            color: "#9aa5b1",
          },
        },
      },
    },
    plugins: [
      {
        id: "structureOverlay",
        beforeDraw(chart) {
          drawStructureOverlay(chart, markers);
        },
      },
    ],
  });
}

function drawStructureOverlay(chart, markers) {
  const { ctx, chartArea, scales } = chart;
  if (!chartArea || !markers?.length) {
    return;
  }

  ctx.save();

  for (const marker of markers) {
    const x = scales.x.getPixelForValue(Number(marker.time));
    const color = markerColor(marker.type);

    if (marker.end_time != null) {
      const x2 = scales.x.getPixelForValue(Number(marker.end_time));
      ctx.fillStyle = color.fill;
      ctx.fillRect(x, chartArea.top + 6, Math.max(2, x2 - x), chartArea.bottom - chartArea.top - 12);
    }

    ctx.strokeStyle = color.stroke;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = color.stroke;
    ctx.beginPath();
    ctx.arc(x, chartArea.top + 10, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

function renderEmptyState() {
  elements.summaryGrid.innerHTML = '<div class="empty-state">No tracks match the current filter.</div>';
  elements.trackList.innerHTML = '<div class="empty-state">No tracks to show.</div>';
  elements.recommendations.innerHTML = '<div class="empty-state">No recommendations.</div>';
  elements.markerList.innerHTML = '<div class="empty-state">No structure markers.</div>';
  elements.selectedTitle.textContent = "No track selected";
  elements.selectedArtist.textContent = "Adjust search or filter criteria";
  elements.selectedBadges.innerHTML = "";
  elements.selectedMetrics.innerHTML = "";
  elements.cueStrip.innerHTML = "";
  elements.markerCount.textContent = "0 markers";
  elements.trackCount.textContent = `0 of ${state.tracks.length} tracks`;

  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }
}

function renderError(error) {
  const message = `Unable to load tracklist data: ${escapeHtml(error.message)}`;
  elements.summaryGrid.innerHTML = `<div class="empty-state">${message}</div>`;
  elements.trackList.innerHTML = `<div class="empty-state">${message}</div>`;
  elements.recommendations.innerHTML = `<div class="empty-state">${message}</div>`;
  elements.markerList.innerHTML = `<div class="empty-state">${message}</div>`;
  elements.selectedTitle.textContent = "Load error";
  elements.selectedArtist.textContent = "Serve this folder over HTTP to load the JSON file.";
  elements.trackCount.textContent = "0 tracks";
}

function searchTrack(track, query) {
  const haystack = [track.artist, track.title, track.key, track.camelot, String(track.bpm)].join(" ").toLowerCase();
  return haystack.includes(query);
}

function matchesPreset(track, filterId) {
  if (filterId === "all") {
    return true;
  }

  if (filterId === "high-energy") {
    return Number(track.avg_energy_level) >= 8;
  }

  if (filterId === "trancey") {
    return Number(track.bpm) >= 128 && Number(track.bpm) <= 145;
  }

  if (filterId === "slow-burn") {
    return Number(track.bpm) < 100;
  }

  return true;
}

function compatibilityScore(base, candidate) {
  const bpmDiff = Math.abs(Number(base.bpm) - Number(candidate.bpm));
  const energyDiff = Math.abs(Number(base.avg_energy_level) - Number(candidate.avg_energy_level));
  const harmonic = harmonicCompatibility(base, candidate) ? 1 : 0;
  const bpmScore = clamp(100 - bpmDiff * 6, 0, 100);
  const energyScore = clamp(100 - energyDiff * 12, 0, 100);
  const harmonyScore = harmonic ? 100 : 30;
  return bpmScore * 0.4 + energyScore * 0.25 + harmonyScore * 0.35;
}

function harmonicCompatibility(base, candidate) {
  const baseCamelot = parseCamelot(base.camelot);
  const candidateCamelot = parseCamelot(candidate.camelot);
  if (!baseCamelot || !candidateCamelot) {
    return false;
  }

  const sameKey = base.camelot === candidate.camelot;
  const relative = baseCamelot.number === candidateCamelot.number && baseCamelot.mode !== candidateCamelot.mode;
  const adjacent =
    baseCamelot.mode === candidateCamelot.mode &&
    (Math.abs(baseCamelot.number - candidateCamelot.number) === 1 || Math.abs(baseCamelot.number - candidateCamelot.number) === 11);

  return sameKey || relative || adjacent;
}

function harmonicNote(base, candidate) {
  if (base.camelot === candidate.camelot) {
    return "Same Camelot lane, ideal for a clean harmonic blend.";
  }

  const baseCamelot = parseCamelot(base.camelot);
  const candidateCamelot = parseCamelot(candidate.camelot);
  if (!baseCamelot || !candidateCamelot) {
    return "Use as an energy match and confirm by ear.";
  }

  if (baseCamelot.number === candidateCamelot.number && baseCamelot.mode !== candidateCamelot.mode) {
    return "Relative major/minor pair, good for a compatible mood change.";
  }

  return "Adjacent Camelot value, suitable if the energy trajectory lines up.";
}

function parseCamelot(camelot) {
  const match = String(camelot || "").match(/^(\d{1,2})([AB])$/i);
  if (!match) {
    return null;
  }

  return {
    number: Number(match[1]),
    mode: match[2].toUpperCase(),
  };
}

function markerColor(type) {
  if (type === "drop") {
    return {
      stroke: "rgba(242, 162, 58, 0.8)",
      fill: "rgba(242, 162, 58, 0.08)",
    };
  }

  if (type === "peak_section") {
    return {
      stroke: "rgba(76, 215, 165, 0.8)",
      fill: "rgba(76, 215, 165, 0.06)",
    };
  }

  if (type === "build_up") {
    return {
      stroke: "rgba(94, 120, 255, 0.82)",
      fill: "rgba(94, 120, 255, 0.06)",
    };
  }

  if (type === "breakdown") {
    return {
      stroke: "rgba(240, 109, 95, 0.82)",
      fill: "rgba(240, 109, 95, 0.05)",
    };
  }

  return {
    stroke: "rgba(184, 194, 204, 0.65)",
    fill: "rgba(184, 194, 204, 0.05)",
  };
}

function markerDescription(type) {
  const descriptions = {
    drop: "Impact point where energy resolves into the main groove.",
    peak_section: "Sustained high-energy plateau with the biggest mix window.",
    build_up: "Tension rise leading into a transition or drop.",
    build_down: "Controlled energy fall for phrase ending or mix-out.",
    breakdown: "Low-energy stretch for phrasing, reset, or atmospheric blends.",
  };

  return descriptions[type] || "Detected structural event.";
}

function structureSpanText(track) {
  const markers = track.structure_markers || [];
  const peakCount = countMarkers(track, "peak_section");
  const dropCount = countMarkers(track, "drop");
  return `${peakCount} peaks / ${dropCount} drops / ${markers.length} total`;
}

function peakWindow(track) {
  const peaks = (track.structure_markers || []).filter((marker) => marker.type === "peak_section");
  if (!peaks.length) {
    return "No peak section detected";
  }

  const first = peaks[0];
  return `${formatSeconds(first.time)} to ${formatSeconds(first.end_time ?? first.time)}`;
}

function outroCue(track) {
  const down = (track.structure_markers || []).find((marker) => marker.type === "build_down");
  if (!down) {
    return "No build-down detected";
  }

  return `${formatSeconds(down.time)} to ${formatSeconds(down.end_time ?? down.time)}`;
}

function firstDropTime(track) {
  const marker = (track.structure_markers || []).find((entry) => entry.type === "drop");
  return marker ? Number(marker.time) : Number.NaN;
}

function countMarkers(track, type) {
  return (track.structure_markers || []).filter((marker) => marker.type === type).length;
}

function average(values) {
  if (!values.length) {
    return 0;
  }

  return values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function formatSeconds(seconds) {
  if (!Number.isFinite(Number(seconds))) {
    return "n/a";
  }

  const total = Math.max(0, Math.round(Number(seconds)));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
