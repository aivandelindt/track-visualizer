const DEFAULT_DATA_URL = "output/tracklist_analysis.json";
const ANALYZE_ENDPOINT = "/api/analyze";
const TRACKS_ENDPOINT = "/api/tracks";

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
  queryTimer: null,
  backendQueryEnabled: true,
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
    "compactMarkerList",
    "compactMarkerCount",
    "compactRecommendationList",
    "compactRecommendationCount",
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
    scheduleFilterApply();
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
  setAnalysisStatus("Loading track library...", "idle");

  try {
    const payload = await fetchTracksFromApi();
    setTracks(payload.tracks || [], {
      label: payload.source?.label || TRACKS_ENDPOINT,
      folder: payload.source?.folder || "Bundled sample JSON",
      genre: payload.source?.genre || elements.genreSelect.value,
      fileCount: payload.source?.fileCount || (payload.tracks || []).length,
      mode: payload.source?.mode || "sample",
    });
    setAnalysisStatus(
      `Loaded ${state.tracks.length} tracks from TinyDB-backed library.`,
      "success",
    );
    return;
  } catch {
    state.backendQueryEnabled = false;
  }

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
    await applyFilters();
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
    button.addEventListener("click", async () => {
      state.filter = button.dataset.filter;
      renderFilters();
      await applyFilters();
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

function scheduleFilterApply() {
  if (state.queryTimer) {
    clearTimeout(state.queryTimer);
  }

  state.queryTimer = setTimeout(() => {
    applyFilters();
  }, 180);
}

async function applyFilters() {
  if (state.backendQueryEnabled) {
    try {
      const previousSelection = state.filteredTracks[state.selectedIndex]?.file;
      const payload = await fetchTracksFromApi({
        search: state.search,
        filter: state.filter,
      });
      state.filteredTracks = payload.tracks || [];

      if (state.filteredTracks.length === 0) {
        state.selectedIndex = 0;
        renderEmptyState();
        return;
      }

      const selectedIndex = state.filteredTracks.findIndex(
        (track) => track.file === previousSelection,
      );
      state.selectedIndex = selectedIndex >= 0 ? selectedIndex : 0;
      renderDashboard();
      return;
    } catch {
      state.backendQueryEnabled = false;
      setAnalysisStatus(
        "Realtime TinyDB queries unavailable; using local filtering mode.",
        "idle",
      );
    }
  }

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

async function fetchTracksFromApi({ search = "", filter = "all" } = {}) {
  const params = new URLSearchParams();
  if (search) {
    params.set("search", search);
  }
  if (filter && filter !== "all") {
    params.set("filter", filter);
  }

  const url = params.toString() ? `${TRACKS_ENDPOINT}?${params.toString()}` : TRACKS_ENDPOINT;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
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
  renderCompactMarkers(selectedTrack);
  renderCompactRecommendations(selectedTrack);
  renderChart(selectedTrack);
}

function renderSummary() {
  const tracks = state.tracks;
  const totalDuration = tracks.reduce((sum, track) => sum + Number(track.duration_sec || 0), 0);
  const bpms = tracks.map((t) => Number(t.bpm || 0)).filter((v) => v > 0);
  const energies = tracks.map((t) => Number(t.avg_energy_level || 0));
  const averageBpm = average(bpms);
  const averageEnergy = average(energies);
  const bpmMin = bpms.length ? Math.min(...bpms) : 0;
  const bpmMax = bpms.length ? Math.max(...bpms) : 0;
  const quickestDrop = Math.min(
    ...tracks.map((track) => firstDropTime(track)).filter((value) => Number.isFinite(value)),
  );
  const totalCues = tracks.reduce((sum, t) => sum + (t.structure_markers || []).length, 0);
  const uniqueKeys = new Set(tracks.map((t) => t.camelot).filter(Boolean)).size;
  const totalMinutes = Math.round(totalDuration / 60);
  const sourceLabel =
    state.source.mode === "uploaded"
      ? `${state.source.folder} · ${state.source.genre}`
      : "Bundled sample JSON";

  const summaryItems = [
    { label: "Tracks", value: `${tracks.length}`, meta: sourceLabel },
    { label: "Avg BPM", value: `${averageBpm.toFixed(1)}`, meta: "Mean across library" },
    {
      label: "BPM Range",
      value: bpms.length ? `${bpmMin.toFixed(0)}–${bpmMax.toFixed(0)}` : "n/a",
      meta: "Min → Max",
    },
    { label: "Avg Energy", value: `${averageEnergy.toFixed(1)}/10`, meta: "Mix intensity" },
    { label: "Total Length", value: `${totalMinutes} min`, meta: `${totalDuration.toFixed(0)}s raw` },
    {
      label: "Fastest Drop",
      value: Number.isFinite(quickestDrop) ? `${quickestDrop.toFixed(1)}s` : "n/a",
      meta: "Earliest cue point",
    },
    { label: "Cue Points", value: `${totalCues}`, meta: "Structure markers" },
    { label: "Keys", value: `${uniqueKeys}`, meta: "Unique Camelot positions" },
  ];

  const summaryTitle = document.getElementById("summaryTitle");
  if (summaryTitle) {
    summaryTitle.textContent = `${tracks.length} track${tracks.length !== 1 ? "s" : ""} — TinyDB`;
  }

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
      const camelotClr = camelotColor(track.camelot);
      return `
        <article class="track-card ${isActive ? "is-active" : ""}" data-index="${index}">
          <div class="track-topline">
            <div>
              <h3 class="track-name">${escapeHtml(track.title)}</h3>
              <p class="track-artist">${escapeHtml(track.artist)}</p>
            </div>
            <span class="track-chip" style="background:${camelotClr.bg};color:${camelotClr.text}">${track.camelot} · ${track.bpm.toFixed(1)} BPM</span>
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
  const camelotClr = camelotColor(track.camelot);
  elements.selectedBadges.innerHTML = [
    `<span class="pill" style="background:${camelotClr.bg};color:${camelotClr.text}">${track.camelot}</span>`,
    `<span class="pill" style="background:${camelotClr.bg};color:${camelotClr.text};opacity:0.85">${track.key}</span>`,
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

function getRecommendations(track, limit = 4) {
  return state.tracks
    .filter((candidate) => candidate.file !== track.file)
    .map((candidate) => ({
      track: candidate,
      score: compatibilityScore(track, candidate),
    }))
    .sort((left, right) => right.score - left.score)
    .slice(0, limit);
}

function renderRecommendations(track) {
  const recommendations = getRecommendations(track, 4);

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

function renderCompactRecommendations(track) {
  const recommendations = getRecommendations(track, 4);
  elements.compactRecommendationCount.textContent = `${recommendations.length} mixes`;

  if (recommendations.length === 0) {
    elements.compactRecommendationList.innerHTML = '<div class="empty-state">No recommendations available.</div>';
    return;
  }

  elements.compactRecommendationList.innerHTML = recommendations
    .map(({ track: candidate, score }) => {
      const camelotClr = camelotColor(candidate.camelot);
      return `
        <article class="track-card compact-recommendation-card">
          <div class="track-topline">
            <div>
              <h3 class="track-name">${escapeHtml(candidate.title)}</h3>
              <p class="track-artist">${escapeHtml(candidate.artist)}</p>
            </div>
            <span class="track-chip compact-recommendation-score">${score.toFixed(0)}%</span>
          </div>
          <div class="track-tags">
            <span class="track-chip" style="background:${camelotClr.bg};color:${camelotClr.text}">${candidate.camelot} · ${escapeHtml(candidate.key)}</span>
            <span class="track-chip">${candidate.bpm.toFixed(1)} BPM</span>
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
      const clr = markerColor(marker.type);
      return `
        <div class="marker-item" style="border-color:${clr.stroke.replace("0.85", "0.25")};background:${clr.fill}">
          <div class="marker-type" style="color:${clr.text}">${label}</div>
          <div class="marker-sub">${markerDescription(marker.type)}</div>
          <div class="marker-time">${formatSeconds(marker.time)}${marker.end_time ? ` - ${formatSeconds(marker.end_time)}` : ""}</div>
        </div>
      `;
    })
    .join("");
}

function renderCompactMarkers(track) {
  const markers = [...(track.structure_markers || [])].sort((left, right) => Number(left.time) - Number(right.time));
  elements.compactMarkerCount.textContent = `${markers.length} markers`;

  if (markers.length === 0) {
    elements.compactMarkerList.innerHTML = '<div class="empty-state">No structure markers.</div>';
    return;
  }

  const grouped = markers.reduce((acc, marker) => {
    const type = String(marker.type || "event");
    if (!acc.has(type)) {
      acc.set(type, []);
    }

    const endTime = marker.end_time;
    const startTime = formatSeconds(marker.time);
    const endTimeLabel = endTime != null ? formatSeconds(endTime) : null;
    acc.get(type).push({ startTime, endTimeLabel });
    return acc;
  }, new Map());

  elements.compactMarkerList.innerHTML = Array.from(grouped.entries())
    .map(([type, timeLabels]) => {
      const clr = markerColor(type);
      const label = type.replace(/_/g, " ");
      return `
        <article class="compact-marker-group" style="border-color:${clr.stroke.replace("0.85", "0.25")};background:${clr.fill}">
          <div class="compact-marker-type" style="color:${clr.text}">${label}</div>
          <div class="compact-marker-times">
            ${timeLabels
              .map(
                (time) => `<span class="compact-marker-time"><strong class="compact-marker-time-start">${time.startTime}</strong>${time.endTimeLabel ? ` <span class="compact-marker-time-sep">-</span> ${time.endTimeLabel}` : ""}</span>`,
              )
              .join("")}
          </div>
        </article>
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
  elements.compactMarkerList.innerHTML = '<div class="empty-state">No structure markers.</div>';
  elements.selectedTitle.textContent = "No track selected";
  elements.selectedArtist.textContent = "Adjust search or filter criteria";
  elements.selectedBadges.innerHTML = "";
  elements.selectedMetrics.innerHTML = "";
  elements.cueStrip.innerHTML = "";
  elements.markerCount.textContent = "0 markers";
  elements.compactMarkerCount.textContent = "0 markers";
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
  elements.compactMarkerList.innerHTML = `<div class="empty-state">${message}</div>`;
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

// Camelot System Wheel colors — hue follows the wheel's rainbow arc (12 o'clock → clockwise)
const CAMELOT_COLORS = {
  "1A":  { bg: "rgba(200, 35,  55,  0.16)", text: "#e88090" },
  "1B":  { bg: "rgba(230, 48,  65,  0.16)", text: "#ff9ea8" },
  "2A":  { bg: "rgba(195, 65,  30,  0.16)", text: "#e89a70" },
  "2B":  { bg: "rgba(228, 85,  42,  0.16)", text: "#ffb07e" },
  "3A":  { bg: "rgba(195, 125, 22,  0.16)", text: "#e8c870" },
  "3B":  { bg: "rgba(222, 158, 32,  0.16)", text: "#ffe07c" },
  "4A":  { bg: "rgba(152, 168, 22,  0.16)", text: "#d0dc60" },
  "4B":  { bg: "rgba(188, 208, 28,  0.16)", text: "#eaf67c" },
  "5A":  { bg: "rgba(82,  162, 32,  0.16)", text: "#90d870" },
  "5B":  { bg: "rgba(102, 202, 52,  0.16)", text: "#a8ea70" },
  "6A":  { bg: "rgba(32,  162, 102, 0.16)", text: "#58e0a8" },
  "6B":  { bg: "rgba(42,  202, 132, 0.16)", text: "#68f2ba" },
  "7A":  { bg: "rgba(32,  142, 182, 0.16)", text: "#58caf2" },
  "7B":  { bg: "rgba(42,  172, 222, 0.16)", text: "#6ae0ff" },
  "8A":  { bg: "rgba(62,  82,  202, 0.16)", text: "#889afc" },
  "8B":  { bg: "rgba(82,  112, 242, 0.16)", text: "#a0beff" },
  "9A":  { bg: "rgba(82,  52,  192, 0.16)", text: "#aa8af2" },
  "9B":  { bg: "rgba(102, 72,  222, 0.16)", text: "#bca2ff" },
  "10A": { bg: "rgba(122, 32,  182, 0.16)", text: "#ca6afa" },
  "10B": { bg: "rgba(152, 42,  212, 0.16)", text: "#dc8aff" },
  "11A": { bg: "rgba(172, 22,  142, 0.16)", text: "#e25aca" },
  "11B": { bg: "rgba(202, 32,  162, 0.16)", text: "#ff72da" },
  "12A": { bg: "rgba(192, 22,  92,  0.16)", text: "#e85aaa" },
  "12B": { bg: "rgba(222, 32,  102, 0.16)", text: "#ff72bc" },
};

function camelotColor(camelot) {
  const key = String(camelot || "").toUpperCase().trim();
  return CAMELOT_COLORS[key] || { bg: "rgba(242, 162, 58, 0.14)", text: "#ffd79a" };
}

const MARKER_COLORS = {
  drop:          { stroke: "rgba(242, 162,  58, 0.85)", fill: "rgba(242, 162,  58, 0.08)", text: "#ffd79a" },
  peak_section:  { stroke: "rgba(76,  215, 165, 0.85)", fill: "rgba(76,  215, 165, 0.07)", text: "#9bf0ce" },
  build_up:      { stroke: "rgba(94,  120, 255, 0.85)", fill: "rgba(94,  120, 255, 0.07)", text: "#a0b0ff" },
  build_down:    { stroke: "rgba(240,  90, 188, 0.85)", fill: "rgba(240,  90, 188, 0.07)", text: "#f898d8" },
  breakdown:     { stroke: "rgba(240, 109,  95, 0.85)", fill: "rgba(240, 109,  95, 0.06)", text: "#ffb1a8" },
};

const MARKER_COLORS_DEFAULT = { stroke: "rgba(184, 194, 204, 0.65)", fill: "rgba(184, 194, 204, 0.05)", text: "#c8d0d8" };

function markerColor(type) {
  return MARKER_COLORS[type] || MARKER_COLORS_DEFAULT;
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
