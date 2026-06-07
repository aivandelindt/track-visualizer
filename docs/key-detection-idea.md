*Thinking...*

>  I need to find audio processing libraries that can detect musical keys in tracks, then build a JavaScript frontend with a Python backend API to handle the analysis.
>
>  I've gathered enough information to put together a full solution. The key insight is that the user wants to detect key changes throughout a song, so I'll need to segment the audio and analyze each section separately using librosa's chromagram features with the Krumhansl-Schmuckler algorithm, then build both a Python backend and JavaScript frontend to handle the analysis and visualization.

I'll research audio processing modules for key detection, then build you a complete solution.Based on my research, here's an overview of the available modules followed by a complete working solution.

## Module Options

The dominant tool in this space is **librosa** (Python). To detect the musical key, you use the Chroma Short-Time Fourier Transform (chroma_stft), a feature extraction technique where the chroma feature represents the energy distribution of the twelve different pitch classes in music.[[1]](https://medium.com/@oluyaled/detecting-musical-key-from-audio-using-chroma-feature-in-python-72850c0ae4b1) The most established algorithm built on top of this is **Krumhansl-Schmuckler**. A chromagram represents the likelihood of the chroma occurrences in the audio. This chromagram is correlated with Krumhansl's key profiles that represent the perceived stability of each chroma within the context of a particular musical key. The key profile that has maximum correlation with the computed chromagram is taken as the most likely key.[[9]](https://www.ee.columbia.edu/~dpwe/ismir2004/CRFILES/paper142.pdf)

A quick summary of the main candidates:

- **librosa + Krumhansl-Schmuckler (recommended)** — Pure Python, flexible. The Krumhansl-Schmuckler key-finding algorithm is a widely-used computational model based on the concept of tonal hierarchies, which posits that certain tones are perceived as more stable or central within a given key, computing the most likely key by comparing the distribution of pitch classes in the music to pre-defined key profiles.[[5]](https://github.com/Corentin-Lcs/music-key-finder) Its accuracy is solid: an evaluation with 237 CD recordings indicated a classification accuracy of 75.1%, and by considering exact, relative, dominant, sub-dominant and parallel keys as similar, the accuracy is even 94.1%.[[9]](https://www.ee.columbia.edu/~dpwe/ismir2004/CRFILES/paper142.pdf)

- **pymusickit** (PyPI) — A pip-installable wrapper around the above. You install with `pip install pymusickit`, then `from pymusickit.key_finder import KeyFinder`, create `song = KeyFinder(audio_path)` with optional `t_start, t_end` parameters in seconds, and call methods like `song.print_key()`.[[4]](https://pypi.org/project/pymusickit/)

- **keyfinder** (PyPI) — Python bindings to the C++ **libKeyFinder** library. This package implements bindings for libKeyFinder, including supporting libav code for reading audio data. You call `keyfinder.key('my-audio.mp3')` and can get `.camelot()` notation (e.g. 11B).[[6]](https://pypi.org/project/keyfinder/) Camelot notation is especially useful for DJ/harmonic-mixing apps.

**Important for your "all keys within a track" requirement:** A single song often modulates between keys. In a complex piece like Ravel's "Une Barque sur l'Ocean," there are several sections with different keys, which you can learn by loading it with librosa and passing it to a Tonal_Fragment class.[[6]](https://github.com/jackmcarthur/musical-key-finder) So rather than reporting one global key, the solution below **slices the track into time windows and detects the key of each window**, giving you a timeline of all keys.

---

## Architecture

```
[Browser / JS frontend]  ──upload audio──►  [Python FastAPI server]
       ▲                                            │
       │                                     librosa + K-S algorithm
       │                                     (windowed analysis)
       └──────── JSON: key timeline ◄──────────────┘
```

---

## 1. Backend — Python (FastAPI + librosa)

This server accepts an uploaded audio file, splits it into windows, and runs the Krumhansl-Schmuckler algorithm per window to return a full timeline of detected keys.

```python
# app.py
# pip install fastapi uvicorn librosa numpy python-multipart soundfile
# (mp3 support requires ffmpeg installed on the system)

import io
import tempfile
import numpy as np
import librosa
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Key Detection API")

# Allow the JS frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten this in production
    allow_methods=["*"],
    allow_headers=["*"],
)

PITCHES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Krumhansl-Schmuckler key profiles (major + minor)
MAJ_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MIN_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


def detect_key_from_chroma(chroma_vector: np.ndarray):
    """Return (best_key, quality, confidence, all_scores) via K-S correlation."""
    scores = {}
    for i in range(12):
        # rotate profiles so each tonic is tested
        maj = np.corrcoef(np.roll(MAJ_PROFILE, i), chroma_vector)[0, 1]
        minr = np.corrcoef(np.roll(MIN_PROFILE, i), chroma_vector)[0, 1]
        scores[f"{PITCHES[i]} major"] = float(maj)
        scores[f"{PITCHES[i]} minor"] = float(minr)

    best = max(scores, key=scores.get)
    sorted_scores = sorted(scores.values(), reverse=True)
    # confidence = gap between best and second-best correlation
    confidence = float(sorted_scores[0] - sorted_scores[1])
    name, quality = best.rsplit(" ", 1)
    return name, quality, confidence, scores


def analyze_track(y, sr, window_sec=10.0, hop_sec=5.0):
    """Slide a window across the track and detect key per window."""
    # Separate harmonic content for cleaner key estimation
    y_harmonic, _ = librosa.effects.hpss(y)

    win = int(window_sec * sr)
    hop = int(hop_sec * sr)
    total = len(y_harmonic)
    results = []

    for start in range(0, max(total - win, 1), hop):
        segment = y_harmonic[start:start + win]
        if len(segment) < sr:  # skip tiny tail segments
            continue
        chroma = librosa.feature.chroma_cqt(
            y=segment, sr=sr, bins_per_octave=24
        )
        mean_chroma = np.mean(chroma, axis=1)
        key, quality, conf, _ = detect_key_from_chroma(mean_chroma)
        results.append({
            "start": round(start / sr, 2),
            "end": round(min(start + win, total) / sr, 2),
            "key": key,
            "quality": quality,
            "confidence": round(conf, 4),
        })

    # Global key across the whole track
    full_chroma = np.mean(
        librosa.feature.chroma_cqt(y=y_harmonic, sr=sr, bins_per_octave=24),
        axis=1,
    )
    g_key, g_quality, g_conf, all_scores = detect_key_from_chroma(full_chroma)

    # Collapse the timeline into contiguous key "segments"
    segments = []
    for r in results:
        label = f"{r['key']} {r['quality']}"
        if segments and segments[-1]["label"] == label:
            segments[-1]["end"] = r["end"]
        else:
            segments.append({
                "label": label,
                "start": r["start"],
                "end": r["end"],
            })

    # Distinct set of all keys found anywhere in the song
    unique_keys = sorted({f"{r['key']} {r['quality']}" for r in results})

    return {
        "global_key": f"{g_key} {g_quality}",
        "global_confidence": round(g_conf, 4),
        "all_keys": unique_keys,
        "segments": segments,
        "windows": results,
        "key_scores": {k: round(v, 4) for k, v in all_scores.items()},
    }


@app.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    window_sec: float = 10.0,
    hop_sec: float = 5.0,
):
    if not file.filename.lower().endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a")):
        raise HTTPException(400, "Unsupported file type")

    data = await file.read()
    # librosa.load needs a path or file-like; use a temp file for broad codec support
    with tempfile.NamedTemporaryFile(suffix=file.filename[-5:]) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            y, sr = librosa.load(tmp.name, sr=22050, mono=True)
        except Exception as e:
            raise HTTPException(400, f"Could not decode audio: {e}")

    if len(y) < sr:
        raise HTTPException(400, "Audio too short to analyze")

    result = analyze_track(y, sr, window_sec=window_sec, hop_sec=hop_sec)
    result["duration"] = round(len(y) / sr, 2)
    result["filename"] = file.filename
    return result


# Run with:  uvicorn app:app --reload --port 8000
```

A few notes on key design choices, drawn from established practice:

- I use `chroma_cqt` with `bins_per_octave=24` because that mirrors the proven reference implementation: `self.chromograph = librosa.feature.chroma_cqt(y=self.y_segment, sr=self.sr, bins_per_octave=24)`, summing each pitch class to get the intensity present in each interval.[[4]](https://github.com/jackmcarthur/musical-key-finder/blob/master/keyfinder.py)
- I run harmonic-percussive separation first (`librosa.effects.hpss`), as in the reference: `y_harmonic, y_percussive = librosa.effects.hpss(y)` before passing `y_harmonic` to the analysis class.[[6]](https://github.com/jackmcarthur/musical-key-finder) This removes drum transients that pollute pitch estimation.
- The profile values match the canonical Krumhansl numbers: `maj_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]`.[[4]](https://github.com/jackmcarthur/musical-key-finder/blob/master/keyfinder.py)

---

## 2. Frontend — JavaScript

Plain HTML/JS with `fetch` and `FormData`. Drop this in any static file or framework component.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Song Key Detector</title>
<style>
  :root { font-family: system-ui, sans-serif; }
  body { max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  h1 { font-size: 1.4rem; }
  .drop { border: 2px dashed #aaa; border-radius: 12px; padding: 2rem;
          text-align: center; cursor: pointer; transition: .2s; }
  .drop.hover { border-color: #4f46e5; background: #f5f3ff; }
  button { background: #4f46e5; color: #fff; border: none; padding: .6rem 1.2rem;
           border-radius: 8px; cursor: pointer; font-size: 1rem; }
  button:disabled { opacity: .5; cursor: default; }
  .global { font-size: 1.6rem; font-weight: 700; margin: 1rem 0; }
  .chips span { display: inline-block; background: #eef2ff; color: #4338ca;
                padding: .25rem .6rem; border-radius: 999px; margin: .2rem; }
  .timeline { margin-top: 1rem; }
  .seg { display: flex; align-items: center; gap: .75rem; padding: .4rem 0;
         border-bottom: 1px solid #eee; }
  .bar { height: 10px; background: #4f46e5; border-radius: 4px; }
  .time { font-variant-numeric: tabular-nums; color: #666; min-width: 110px; }
  .err { color: #b91c1c; }
</style>
</head>
<body>
  <h1>🎵 Song Key Detector</h1>
  <p>Upload a track to detect every key it passes through.</p>

  <div class="drop" id="drop">
    <p>Drag &amp; drop an audio file here, or click to choose</p>
    <input type="file" id="fileInput" accept="audio/*" hidden>
  </div>

  <p>
    <button id="analyzeBtn" disabled>Analyze</button>
    <span id="fileName"></span>
  </p>

  <div id="status"></div>
  <div id="results" hidden>
    <div class="global" id="globalKey"></div>
    <div><strong>All keys found:</strong></div>
    <div class="chips" id="allKeys"></div>
    <div class="timeline" id="timeline"></div>
  </div>

<script>
const API = "http://localhost:8000/analyze";
const drop = document.getElementById("drop");
const input = document.getElementById("fileInput");
const analyzeBtn = document.getElementById("analyzeBtn");
const fileNameEl = document.getElementById("fileName");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
let selectedFile = null;

drop.addEventListener("click", () => input.click());
drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("hover"); });
drop.addEventListener("dragleave", () => drop.classList.remove("hover"));
drop.addEventListener("drop", e => {
  e.preventDefault(); drop.classList.remove("hover");
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
input.addEventListener("change", () => { if (input.files.length) setFile(input.files[0]); });

function setFile(f) {
  selectedFile = f;
  fileNameEl.textContent = f.name;
  analyzeBtn.disabled = false;
}

analyzeBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  analyzeBtn.disabled = true;
  resultsEl.hidden = true;
  statusEl.innerHTML = "Analyzing… (this can take a few seconds)";

  const form = new FormData();
  form.append("file", selectedFile);

  try {
    const res = await fetch(API, { method: "POST", body: form });
    if (!res.ok) {
      const msg = await res.text();
      throw new Error(msg || res.statusText);
    }
    const data = await res.json();
    render(data);
    statusEl.textContent = "";
  } catch (err) {
    statusEl.innerHTML = `<p class="err">Error: ${err.message}</p>`;
  } finally {
    analyzeBtn.disabled = false;
  }
});

function render(data) {
  resultsEl.hidden = false;
  document.getElementById("globalKey").textContent =
    `Primary key: ${data.global_key}  (conf ${data.global_confidence})`;

  const chips = document.getElementById("allKeys");
  chips.innerHTML = "";
  data.all_keys.forEach(k => {
    const s = document.createElement("span");
    s.textContent = k;
    chips.appendChild(s);
  });

  const tl = document.getElementById("timeline");
  tl.innerHTML = "<h3>Key timeline</h3>";
  const dur = data.duration || 1;
  data.segments.forEach(seg => {
    const row = document.createElement("div");
    row.className = "seg";
    const widthPct = ((seg.end - seg.start) / dur) * 100;
    row.innerHTML = `
      <span class="time">${fmt(seg.start)}–${fmt(seg.end)}</span>
      <div class="bar" style="width:${Math.max(widthPct, 4)}%"></div>
      <strong>${seg.label}</strong>`;
    tl.appendChild(row);
  });
}

function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
</script>
</body>
</html>
```

---

## Running it

1. **Install backend deps:** `pip install fastapi uvicorn librosa numpy python-multipart soundfile`. For MP3 you also need ffmpeg on the system, since analysis of .mp3 files does require FFmpeg to be installed, but .wav and other files can be analyzed by Librosa without it.[[6]](https://github.com/jackmcarthur/musical-key-finder)
2. **Start the API:** `uvicorn app:app --reload --port 8000`
3. **Open the HTML** file in a browser (serve it via any static server so CORS/fetch behave predictably).

---

## Choosing between approaches

If you want **minimal code** and don't need a custom timeline, swap the backend's analysis for **pymusickit**, which exposes the same algorithm with per-segment options via `t_start`/`t_end` so you can loop over time ranges yourself. If your app is **DJ/harmonic-mixing oriented**, the **keyfinder** (libKeyFinder C++ bindings) gives you Camelot notation out of the box, which is the standard for beatmatching by key.

One realistic caveat worth keeping in mind: the chroma + Krumhansl approach works best on tonal Western music, and as one experimental detector author candidly notes, such tools are not intended for analyzing complex or "real" music featuring multiple instruments, dense mixes, or noisy recordings.[[9]](https://github.com/mrueda/music-key-detector) For production-grade accuracy on commercial mixes, the CNN/deep-learning approaches (like the PyTorch key-class + key-quality models) tend to outperform the classic correlation method, at the cost of needing a trained model.

Would you like me to adapt the backend to use **pymusickit** or the **libKeyFinder Camelot** output instead, or add live audio-playback sync to the timeline?

---
Learn more:
1. [Detecting Musical Key from Audio Using Chroma Feature in Python | by David Oluyale | Medium](https://medium.com/@oluyaled/detecting-musical-key-from-audio-using-chroma-feature-in-python-72850c0ae4b1)
2. [API Final Project](https://api-final-project.vercel.app/)
3. [GitHub - pnlong/determine\_key: Determine the musical key of a given audio sample. · GitHub](https://github.com/pnlong/determine_key)
4. [Chromagram with logarithmic compression](https://groups.google.com/g/librosa/c/p_n_E8_cQds)
5. [pymusickit · PyPI](https://pypi.org/project/pymusickit/)
6. [musical-key-finder/keyfinder.py at master · jackmcarthur/musical-key-finder](https://github.com/jackmcarthur/musical-key-finder/blob/master/keyfinder.py)
7. [GitHub - libraz/bpm-detector: A Python tool for automatic detection of BPM (tempo) and musical key from audio files. · GitHub](https://github.com/libraz/bpm-detector)
8. [GitHub - Corentin-Lcs/music-key-finder: Krumhansl-Schmuckler Key-Finding Algorithm · GitHub](https://github.com/Corentin-Lcs/music-key-finder)
9. [GitHub - jackmcarthur/musical-key-finder: A python project that uses several standard/otherwise very common libraries to determine the key that a song (an .mp3) is in, i.e. F major or C# minor, with annotations and some examples. · GitHub](https://github.com/jackmcarthur/musical-key-finder)
10. [keyfinder · PyPI](https://pypi.org/project/keyfinder/)
11. [jcarbonnell/key\_class\_detection · Hugging Face](https://huggingface.co/jcarbonnell/key_class_detection)
12. [Add Key Detection Algorithms to librosa · Issue #366 · librosa/librosa](https://github.com/librosa/librosa/issues/366)
13. [\[1910.02049\] MIDI Miner – A Python Library for tonal tension and track classification](https://ar5iv.labs.arxiv.org/html/1910.02049)
14. [Chord Colourizer: A Near Real-Time System for Visualizing Musical Key](https://arxiv.org/pdf/2510.10173)
15. [GitHub - mrueda/music-key-detector](https://github.com/mrueda/music-key-detector)
16. [MUSICAL KEY EXTRACTION FROM AUDIO Steffen Pauws](https://www.ee.columbia.edu/~dpwe/ismir2004/CRFILES/paper142.pdf)
17. [Audio processing techniques for semantic audio recognition and report generation](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9812109)
