# CDJ3000x Track Intelligence

Deck-style visualizer for Beatport tracklist analysis JSON. The dashboard reads `output/tracklist_analysis.json` by default and can re-run analysis from a selected audio folder through the local `server.py` bridge.

`server.py` now persists the active track library in TinyDB (`output/track_cache.json`) and serves filtered/searchable results through `GET /api/tracks`.

## What it shows

- Track library with search and energy filters
- Selected-track deck with BPM, key, Camelot, duration, and cue cards
- Energy timeline with structure markers
- Mix recommendations based on harmonic and tempo compatibility
- Folder upload workflow for fresh analysis through `POST /api/analyze`
- A/B compare scoring through `GET /api/compare`
- Similar-track ranking through `GET /api/similar`
- Playlist seed progression generation through `GET /api/playlist-seed`

## Run it

Start the local server and open the dashboard:

```bash
./start.sh
```

Stop the local server:

```bash
./stop.sh
```

If you want to launch the server manually, run:

```bash
python server.py
```

Then open:

```text
http://127.0.0.1:8000/index.html
```

## Analyze a folder

1. Click **Select audio folder** in the dashboard.
2. Choose a folder of audio files.
3. Pick the genre preset, usually `trance` or `techno`.
4. Click **Analyze selection**.

The browser sends the selected files to `server.py`, which writes them to a temporary input folder, runs `analyze.py`, and returns the refreshed track JSON to the UI.
The server also replaces the TinyDB track table with those results, so subsequent search/filter operations query the stored library.

## TinyDB query endpoint

When served through `server.py`, the dashboard uses:

- `GET /api/tracks` - return full stored library (seeded from bundled JSON on first request)
- `GET /api/tracks?search=<text>&filter=<id>` - query TinyDB by free-text and filter id

Supported filter ids match the UI controls:

- `all`
- `high-energy`
- `trancey`
- `slow-burn`

## Comparison and recommendation endpoints

The dashboard and API support track-to-track DJ workflow analysis:

- `GET /api/compare?left=<file>&right=<file>`
- `GET /api/similar?file=<file>&limit=10`
- `GET /api/playlist-seed?file=<file>&limit=8`

### `GET /api/compare`

Returns pairwise metrics for one track pair:

- `similarity_score` (0-100)
- `components` (`timbre`, `spectral`, `tempo`, `key`, `loudness_dynamics`)
- `deltas` (`bpm`, `lufs`, `lra_lu`, `crest_factor_db`, `spectral_centroid_hz`)
- `tags` (for example: `harmonic`, `tempo-safe`, `energy-shift`, `tempo-risk`)
- `mastering` (`overall`, `flags`, `recommendations`, `thresholds`)
- `dj_workflow` (transition guidance fields, documented below)

### `GET /api/similar`

Returns top matches for a source track, sorted by descending `similarity_score`.
Each result includes:

- `track` identity metadata
- `similarity_score`
- `components`
- `tags`
- `dj_workflow`

### `GET /api/playlist-seed`

Builds an ordered progression from a seed track while penalizing abrupt transitions.

Constraints:

- `limit >= 2`
- `limit <= 25`

Response includes:

- `source` (seed track identity)
- `playlist` (ordered track identities)
- `transitions` (one per hop)

Each transition includes:

- `similarity_score`
- `components`
- `tags`
- `dj_workflow`
- `ranking` (`score`, `hard_jump`)

## DJ workflow payload (`dj_workflow`)

The `dj_workflow` object appears in compare/similar/playlist responses:

- `harmonic_mix`: boolean quick flag for harmonic compatibility
- `harmonic`:
	- `compatible`
	- `score`
	- `relation` (`neighbor-compatible`, `relative-compatible`, `workable`, `off-lane`)
	- `tag` (`harmonic` or `harmonic-risk`)
- `bpm_transition`:
	- `recommendation` (`straight mix`, `small nudge`, `risky`)
	- `bpm_delta`
	- `thresholds`
	- `tag` (`tempo-safe`, `tempo-nudge`, `tempo-risk`)
- `energy_transition`:
	- `classification` (`steady`, `energy-shift`, `energy-risk`)
	- `direction` (`up`, `down`, `flat`)
	- `energy_delta`
	- `thresholds`
	- `tag`
- `tags`: deduplicated workflow tags for rendering and rule checks

## Testing

Run the server unit/API behavior tests:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

Current test coverage includes:

- Unit behavior for compare and transition classification helpers
- Sorted similar-track behavior and source exclusion
- Playlist seed progression and transition payload shape
- API handler validation and response shape for compare/similar/playlist-seed

## Repository layout

- `index.html` - page structure
- `styles.css` - deck-style presentation
- `app.js` - data loading and interaction logic
- `server.py` - local HTTP server and analysis endpoint
- `analyze.py` - audio analysis pipeline
- `output/tracklist_analysis.json` - bundled analysis data
- `start.sh` / `stop.sh` - local launch helpers

## Notes

- The UI prefers the bundled JSON on first load so it works immediately over HTTP.
- Folder analysis requires running through `server.py`; the static page does not execute Python directly.
- On macOS, `start.sh` opens the dashboard automatically after starting the server.

## Todo

- Add more cue types and structure markers to the JSON and UI
- Implement energy trend chart with D3 or Chart.js
- Enhance mix recommendations with more detailed compatibility scoring
- Improve mobile responsiveness and touch interactions
- Add error handling and status messaging for the analysis workflow
