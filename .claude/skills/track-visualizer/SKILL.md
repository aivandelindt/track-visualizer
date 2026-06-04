---
name: track-visualizer
description: >
  Create and extend a CDJ3000x-style track visualizer with TinyDB-backed
  track storage/query and local folder-upload analysis via server.py. Use when
  the user asks for track visualizer changes, CDJ3000x UI updates, TinyDB query
  integration, or dashboard extensions for cues, filters, and recommendations.
license: MIT
metadata:
  author: dvandelindt
  version: "1.2.0"
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash
  - Browser
  - Questions
---

# Track Visualizer

Create or extend a CDJ3000x-style dashboard for Beatport analysis JSON with
server-backed analysis and TinyDB-backed querying.

## Inputs

- `$request`: What to visualize, extend, or restyle
- `$tracklist_json`: Path to analysis JSON, usually `output/tracklist_analysis.json`
- `$audio_folder`: Optional folder of source audio files to analyze through the UI
- `$genre`: Optional analyzer preset, usually `trance` or `techno`
- `$output_dir`: Directory containing UI/backend files, usually repo root
- `$tinydb_path`: TinyDB file path, usually `output/track_cache.json`

## Goal

Ship a polished deck-style dashboard that reads bundled JSON, can run fresh analysis
from a selected audio folder through `server.py`, persists active tracks in TinyDB,
supports searchable/filterable querying, and validates cleanly in a browser with no
runtime/server errors.

## Steps

### 1. Inspect data shape and backend flow

Read the active analysis JSON and summary artifacts to confirm the fields used by UI
and backend: `bpm`, `camelot`, `key`, `duration_sec`, `avg_energy_level`, `energy_levels`,
`structure_markers`, `artist`, and `title`.

Inspect `server.py` and `analyze.py` flow for:
- `POST /api/analyze` upload handling
- `python analyze.py --input <FOLDER> --output <DIR> --genre <preset>`
- TinyDB persistence/query points (seed, replace, and filtered search)

If TinyDB behavior is being changed, consult Context7 TinyDB docs first and follow
documented query/update patterns.

**Success criteria**: You can name the exact fields used and identify how default load
and upload-driven analysis map into backend endpoints and TinyDB state.

### 2. Update visual layout and source controls

Update `index.html`, `styles.css`, and `app.js` while preserving the established dark
CDJ/Pioneer visual language. Keep or extend:
- selected-track deck
- library rail
- cue cards
- energy timeline
- source panel (folder select, preset, status)

Do not replace the visual theme unless explicitly requested.

**Success criteria**: The page loads with all major panels visible and source controls
usable on desktop and mobile layouts.

### 3. Wire interactions and TinyDB-backed querying

Implement or extend interactions for:
- search
- filters
- track selection
- recommendations
- structure marker detail display

Route folder analysis through `server.py` only (`POST /api/analyze`). Do not imply browser
execution of `analyze.py`.

For querying:
- prefer `GET /api/tracks` for search/filter against TinyDB
- preserve bundled JSON fallback path for first load or endpoint unavailability
- keep filter IDs aligned across UI and backend

**Success criteria**: Selecting/filtering/searching updates deck/chart/recommendations
without reload, and server-backed querying works when endpoint is available.

### 4. Persist and query track state in TinyDB

Use TinyDB as the active track cache:
- seed from bundled JSON when DB is empty
- replace cached tracks after successful analysis runs
- store source metadata (`folder`, `genre`, `mode`, `fileCount`, `updatedAt`)
- sanitize internal helper fields before API response

Use minimal schema additions and keep response shape compatible with current UI.

**Success criteria**: `GET /api/tracks` returns valid JSON from TinyDB, filtered queries
return expected subsets, and `output/track_cache.json` is created/updated.

### 5. Validate end-to-end in browser and terminal

Run local server startup and verify:
- dashboard HTTP load works
- no runtime/server errors
- API smoke tests pass for both full and filtered queries
- browser interaction reflects search/filter results correctly

Validation checklist:
- start or restart server
- call `GET /api/tracks`
- call `GET /api/tracks?search=<text>&filter=<id>`
- open dashboard and test at least one search and one filter interaction

**Success criteria**: JSON loads over HTTP, dashboard renders and updates correctly,
TinyDB query path is active, and logs show successful endpoint calls.

## Rules

- Preserve existing visual language and component structure unless user asks for a redesign.
- Keep marker details readable in side rails/cards instead of overcrowding chart labels.
- Preserve bundled JSON load path even when adding upload/TinyDB flows.
- Use `server.py` bridge for analyzer execution; never suggest browser runs `analyze.py`.
- Keep changes minimal and focused; avoid unrelated refactors.
- Verify with both terminal API checks and browser interaction before finishing.
