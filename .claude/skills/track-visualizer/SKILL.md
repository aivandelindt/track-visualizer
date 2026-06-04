---
name: track-visualizer
description: >
  Create and extend a CDJ3000x-style track visualizer for Beatport analysis JSON.
  Use when the user says “track visualizer”, “visualize tracklist_analysis.json”,
  “CDJ3000x UI”, or asks how to extend the dashboard.
license: MIT
metadata:
  author: dvandelindt
  version: "1.1.0"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Browser
  - Questions
---

# Track Visualizer

Create or extend a CDJ3000x-style dashboard for Beatport tracklist analysis JSON,
including the local folder-upload workflow backed by `server.py`.

## Inputs

- `$request`: What to visualize, extend, or restyle
- `$tracklist_json`: Path to the analysis JSON, usually `output/tracklist_analysis.json`
- `$audio_folder`: Optional folder of source audio files to analyze through the UI
- `$genre`: Optional analyzer preset, usually `trance` or `techno`
- `$output_dir`: Directory that should contain the UI files, usually the repo root

## Goal

Ship a polished deck-style dashboard that reads the analysis JSON, can trigger fresh analysis
from a selected audio folder, renders track browsing, cue timing, energy trends, and mix
recommendations, and validates cleanly in a browser. Use the same workflow when extending
the visualizer with new cue types, filters, panels, or upload-driven analysis controls.

## Steps

### 1. Inspect the data shape

Read the JSON and any summary artifacts to confirm the fields needed by the UI, especially
`bpm`, `camelot`, `key`, `duration_sec`, `avg_energy_level`, `energy_levels`, and
`structure_markers`. If the request mentions selecting a folder or re-running analysis,
also inspect `server.py` and the `python analyze.py --input <FOLDER_WITH_TRACKS> --output <FOLDER_TO_WRITE_JSON> --genre trance`
flow so the UI changes match the live backend path.

**Success criteria**: You can name the fields the UI will use and identify the default track.

### 2. Design the CDJ-style layout

Build or update `index.html`, `styles.css`, and `app.js` with a dark Pioneer-inspired aesthetic,
a selected-track deck, a library rail, cue cards, an energy timeline chart, and when needed
an analysis source panel for folder upload, preset selection, and status messaging.

**Success criteria**: The page loads and the main panels are visibly present.

### 3. Wire the interactions

Add search, filters, track selection, harmonic compatibility, and structure markers. If the UI
needs to analyze audio folders, route that flow through `server.py` and `POST /api/analyze`
instead of trying to run Python directly from a static page. Keep the chart readable and place
detailed cue text in a rail or card layout when labels would get crowded.

**Success criteria**: Selecting a track updates the deck, chart, and recommendations without a reload.

### 4. Validate in a browser

Serve the folder locally, open the page, and check the data fetch, layout, and interactivity in a browser.
Use `python server.py` when validating folder upload or re-analysis so the browser can call the
local analysis endpoint and still fall back to `output/tracklist_analysis.json` on first load.

**Success criteria**: The JSON loads over HTTP, the visualizer renders without runtime errors,
and when requested a selected audio folder can be analyzed and reflected in the deck without a reload.

### 5. Extend safely

When adding new views, cue types, summary fields, or source controls, preserve the existing visual
language, update the metadata cards and recommendation logic together, and re-run the browser check.

**Success criteria**: New fields appear consistently across the deck, list, chart, recommendation panels,
and any folder-analysis status or source metadata surfaces.

## Rules

- Prefer the existing visual language over introducing a new theme.
- Use current Chart.js guidance before changing chart config or scale behavior.
- Keep marker detail readable in the side rail instead of crowding the chart.
- Preserve the bundled JSON load path even when adding upload-driven analysis.
- Prefer the local `server.py` bridge for analyzer execution; do not imply that the browser can run `analyze.py` directly.
- Make the smallest change that improves the visualizer, then validate it in the browser.
