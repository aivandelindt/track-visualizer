# CDJ3000x Track Intelligence

Deck-style visualizer for Beatport tracklist analysis JSON. The dashboard reads `output/tracklist_analysis.json` by default and can re-run analysis from a selected audio folder through the local `server.py` bridge.

## What it shows

- Track library with search and energy filters
- Selected-track deck with BPM, key, Camelot, duration, and cue cards
- Energy timeline with structure markers
- Mix recommendations based on harmonic and tempo compatibility
- Folder upload workflow for fresh analysis through `POST /api/analyze`

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
