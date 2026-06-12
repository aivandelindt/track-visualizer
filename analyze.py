#!/usr/bin/env python3
"""
DJ Set Analyzer
Scans an audio folder and extracts Camelot key, BPM, energy curve,
and structural markers (build-up, drop, build-down, high-energy/chorus).
Writes results to JSON + CSV for downstream set planning.
"""

import argparse
import csv
import json
import os
from pathlib import Path

import audioread.ffdec
import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from mutagen import File as MutagenFile
from tqdm import tqdm

ANALYSIS_VERSION = "2.0.0"

# ----------------------------------------------------------------------
# Genre presets
# ----------------------------------------------------------------------
PRESETS = {
    "trance": {
        "bpm_min": 128,
        "bpm_max": 145,
        "start_bpm": 138,
        "low_thresh": 0.25,  # breakdowns drop very low
        "high_thresh": 0.70,  # peaks are loud and sustained
        "slope_window_sec": 4.0,
        "riser_weight": 1.0,  # snare rolls / risers are prominent
        "min_drop_gap_sec": 20.0,
    },
    "techno": {
        "bpm_min": 124,
        "bpm_max": 140,
        "start_bpm": 132,
        "low_thresh": 0.35,  # breakdowns are shallower
        "high_thresh": 0.58,  # peaks less dramatic, lower plateau
        "slope_window_sec": 6.0,  # changes are more gradual
        "riser_weight": 0.6,  # fewer obvious risers
        "min_drop_gap_sec": 30.0,
    },
}

# ----------------------------------------------------------------------
# Camelot wheel mapping
# ----------------------------------------------------------------------
# Index = pitch class (C=0 ... B=11)
MAJOR_CAMELOT = {
    0: "8B",
    1: "3B",
    2: "10B",
    3: "5B",
    4: "12B",
    5: "7B",
    6: "2B",
    7: "9B",
    8: "4B",
    9: "11B",
    10: "6B",
    11: "1B",
}
MINOR_CAMELOT = {
    0: "5A",
    1: "12A",
    2: "7A",
    3: "2A",
    4: "9A",
    5: "4A",
    6: "11A",
    7: "6A",
    8: "1A",
    9: "8A",
    10: "3A",
    11: "10A",
}
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles
KS_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
KS_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


def empty_comparison_features():
    return {
        "rms_db": None,
        "lufs": None,
        "lra_lu": None,
        "crest_factor_db": None,
        "spectral_centroid_hz": None,
        "bass_ratio": None,
        "mid_ratio": None,
        "high_ratio": None,
        "stereo_width": None,
        "clipping_ratio": None,
        "transient_sharpness": None,
        "mfcc_mean": None,
        "mfcc_std": None,
    }


def _safe_float(value, precision=4):
    if value is None:
        return None
    value = float(value)
    if not np.isfinite(value):
        return None
    return round(value, precision)


def _db(value, floor=1e-12):
    return 20.0 * np.log10(max(float(value), floor))


def measure_lufs_lra(path):
    audio, rate = sf.read(path, always_2d=True)
    if audio.size == 0:
        return None, None

    # pyloudnorm expects floating point arrays in mono or (samples, channels).
    audio = audio.astype(np.float64, copy=False)
    meter = pyln.Meter(rate)
    lufs = meter.integrated_loudness(audio)
    lra = meter.loudness_range(audio)
    return _safe_float(lufs, 3), _safe_float(lra, 3)


def estimate_stereo_width(path):
    audio, _ = sf.read(path, always_2d=True)
    if audio.size == 0 or audio.shape[1] < 2:
        return None

    left = audio[:, 0].astype(np.float64, copy=False)
    right = audio[:, 1].astype(np.float64, copy=False)
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    mid_rms = np.sqrt(np.mean(mid**2))
    side_rms = np.sqrt(np.mean(side**2))
    if mid_rms <= 1e-12:
        return None
    return _safe_float(side_rms / mid_rms, 4)


def spectral_balance(y, sr, n_fft=2048, hop_length=512):
    S = np.abs(librosa.stft(y=y, n_fft=n_fft, hop_length=hop_length)) ** 2
    if S.size == 0:
        return None, None, None

    power = S.mean(axis=1)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    bass = power[freqs < 100].sum()
    mid = power[(freqs >= 100) & (freqs <= 8000)].sum()
    high = power[freqs > 8000].sum()
    total = bass + mid + high
    if total <= 1e-12:
        return None, None, None

    return (
        _safe_float(bass / total, 5),
        _safe_float(mid / total, 5),
        _safe_float(high / total, 5),
    )


def transient_sharpness(y, sr):
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    if onset_env.size == 0:
        return None
    p95 = np.percentile(onset_env, 95)
    median = np.median(onset_env) + 1e-9
    return _safe_float(p95 / median, 4)


def clipping_ratio(y, threshold=0.999):
    if y.size == 0:
        return None
    return _safe_float(np.mean(np.abs(y) >= threshold), 6)


def mfcc_stats(y, sr, n_mfcc=13):
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
    if mfcc.size == 0:
        return None, None
    mean = np.mean(mfcc, axis=1)
    std = np.std(mfcc, axis=1)
    return [_safe_float(v, 5) for v in mean], [_safe_float(v, 5) for v in std]


def extract_comparison_features(path, y, sr):
    features = empty_comparison_features()
    errors = []

    try:
        rms = np.sqrt(np.mean(np.square(y)))
        features["rms_db"] = _safe_float(_db(rms), 3)
    except Exception as exc:
        errors.append(f"rms_db: {exc}")

    try:
        features["crest_factor_db"] = _safe_float(
            _db(np.max(np.abs(y)) / (np.sqrt(np.mean(np.square(y))) + 1e-12)), 3
        )
    except Exception as exc:
        errors.append(f"crest_factor_db: {exc}")

    try:
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
        features["spectral_centroid_hz"] = _safe_float(float(np.mean(centroid)), 3)
    except Exception as exc:
        errors.append(f"spectral_centroid_hz: {exc}")

    try:
        bass_ratio, mid_ratio, high_ratio = spectral_balance(y, sr)
        features["bass_ratio"] = bass_ratio
        features["mid_ratio"] = mid_ratio
        features["high_ratio"] = high_ratio
    except Exception as exc:
        errors.append(f"spectral_balance: {exc}")

    try:
        lufs, lra = measure_lufs_lra(path)
        features["lufs"] = lufs
        features["lra_lu"] = lra
    except Exception as exc:
        errors.append(f"loudness: {exc}")

    try:
        features["stereo_width"] = estimate_stereo_width(path)
    except Exception as exc:
        errors.append(f"stereo_width: {exc}")

    try:
        features["clipping_ratio"] = clipping_ratio(y)
    except Exception as exc:
        errors.append(f"clipping_ratio: {exc}")

    try:
        features["transient_sharpness"] = transient_sharpness(y, sr)
    except Exception as exc:
        errors.append(f"transient_sharpness: {exc}")

    try:
        mfcc_mean, mfcc_std = mfcc_stats(y, sr)
        features["mfcc_mean"] = mfcc_mean
        features["mfcc_std"] = mfcc_std
    except Exception as exc:
        errors.append(f"mfcc_stats: {exc}")

    return features, errors


def load_audio(path, sr=22050):
    """Robust loader: soundfile first, explicit ffmpeg decoder fallback."""
    try:
        return librosa.load(path, sr=sr, mono=True)
    except Exception:
        with audioread.ffdec.FFmpegAudioFile(path) as aro:
            return librosa.load(aro, sr=sr, mono=True)


def estimate_key(y, sr):
    """Return (camelot, musical_name) using chroma + KS profiles."""
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_mean = chroma.mean(axis=1)
    chroma_mean = chroma_mean / (chroma_mean.sum() + 1e-9)

    best_corr, best_key, best_mode = -np.inf, 0, "major"
    for i in range(12):
        maj = np.corrcoef(np.roll(KS_MAJOR, i), chroma_mean)[0, 1]
        minr = np.corrcoef(np.roll(KS_MINOR, i), chroma_mean)[0, 1]
        if maj > best_corr:
            best_corr, best_key, best_mode = maj, i, "major"
        if minr > best_corr:
            best_corr, best_key, best_mode = minr, i, "minor"

    if best_mode == "major":
        camelot = MAJOR_CAMELOT[best_key]
        name = f"{NOTE_NAMES[best_key]} major"
    else:
        camelot = MINOR_CAMELOT[best_key]
        name = f"{NOTE_NAMES[best_key]} minor"
    return camelot, name


def estimate_bpm(y, sr, preset):
    """BPM constrained to the genre range, with half/double-time correction."""
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, start_bpm=preset["start_bpm"])
    bpm = float(np.atleast_1d(tempo)[0])

    lo, hi = preset["bpm_min"], preset["bpm_max"]
    # Fold half-time / double-time results into the expected window
    while bpm < lo:
        bpm *= 2
    while bpm > hi:
        bpm /= 2
    return round(bpm, 1)


def riser_curve(y, sr, hop_length=512, smooth_sec=1.5):
    """Normalized high-frequency energy (risers, snare rolls, white noise)."""
    S = np.abs(librosa.stft(y, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr)
    band = (freqs >= 6000) & (freqs <= 11000)
    hi = S[band, :].mean(axis=0)

    win = max(1, int((smooth_sec * sr) / hop_length))
    hi = np.convolve(hi, np.ones(win) / win, mode="same")
    return (hi - hi.min()) / (np.ptp(hi) + 1e-9)


def detect_structure(times, norm, riser, preset):
    """
    Trance/techno-aware structure detection.
    Markers: breakdown, build_up, drop, build_down, peak_section.
    """
    markers = []
    dt = times[1] - times[0]
    win = max(1, int(preset["slope_window_sec"] / dt))
    low_t = preset["low_thresh"]
    high_t = preset["high_thresh"]

    deriv = np.gradient(norm, dt)
    deriv = np.convolve(deriv, np.ones(win) / win, mode="same")

    # BREAKDOWN: sustained low-energy plateau (melodic break / groove strip-down)
    breakdown = norm < low_t
    markers += _runs_to_markers(breakdown, times, "breakdown", min_len=int(12.0 / dt))

    # BUILD-UP: rising riser energy AND rising overall energy
    riser_deriv = np.gradient(np.convolve(riser, np.ones(win) / win, mode="same"), dt)
    building = (
        riser_deriv > np.percentile(riser_deriv, 80) * preset["riser_weight"]
    ) & (deriv > 0)
    markers += _runs_to_markers(building, times, "build_up", min_len=int(4.0 / dt))

    # DROP: low/building energy resolving sharply into a high plateau
    in_build, last_drop = False, -1e9
    for i in range(win, len(norm) - win):
        if norm[i] < low_t or building[i]:
            in_build = True
        crossed = norm[i] >= high_t and norm[i - 1] < high_t
        if in_build and crossed and (times[i] - last_drop) > preset["min_drop_gap_sec"]:
            markers.append({"type": "drop", "time": round(times[i], 1)})
            last_drop = times[i]
            in_build = False

    # BUILD-DOWN: sustained energy decline (transition out of a peak)
    falling = deriv < np.percentile(deriv, 12)
    markers += _runs_to_markers(falling, times, "build_down", min_len=win)

    # PEAK SECTION: loud sustained plateau (the "main" / hands-in-the-air part)
    peak = norm >= high_t
    markers += _runs_to_markers(peak, times, "peak_section", min_len=int(16.0 / dt))

    # markers.sort(key=lambda m: m["time"])
    # return _dedupe(markers, gap=4.0)

    # Guard: every marker must be a dict with a numeric "time"
    markers = [m for m in markers if isinstance(m, dict) and "time" in m]
    markers.sort(key=lambda m: float(m["time"]))
    return _dedupe(markers, gap=4.0)


def energy_curve(y, sr, hop_length=512, smooth_sec=2.0):
    """Return (times, normalized_rms 0-1)."""
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    # Smooth with a moving average window
    win = max(1, int((smooth_sec * sr) / hop_length))
    kernel = np.ones(win) / win
    rms_smooth = np.convolve(rms, kernel, mode="same")
    times = librosa.frames_to_time(
        np.arange(len(rms_smooth)), sr=sr, hop_length=hop_length
    )
    norm = (rms_smooth - rms_smooth.min()) / (np.ptp(rms_smooth) + 1e-9)
    return times, norm


def energy_levels(times, norm, segment_sec=10.0):
    """Coarse energy level (1-10) sampled every segment_sec seconds."""
    levels = []
    dur = times[-1]
    t = 0.0
    while t < dur:
        mask = (times >= t) & (times < t + segment_sec)
        if mask.any():
            lvl = int(round(norm[mask].mean() * 9)) + 1  # 1..10
            levels.append({"time": round(t, 1), "level": lvl})
        t += segment_sec
    return levels


def _runs_to_markers(mask, times, label, min_len=1):
    """Convert a boolean mask into markers for each contiguous True run."""
    markers = []
    mask = np.asarray(mask, dtype=bool)
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if (j - i) >= min_len:
                markers.append(
                    {
                        "type": label,
                        "time": round(float(times[i]), 1),
                        "end_time": round(float(times[min(j, n - 1)]), 1),
                    }
                )
            i = j
        else:
            i += 1
    return markers


def _dedupe(markers, gap=4.0):
    """Drop same-type markers occurring within `gap` seconds of each other."""
    out = []
    for m in sorted(markers, key=lambda x: float(x["time"])):
        if not any(
            o["type"] == m["type"] and abs(float(o["time"]) - float(m["time"])) < gap
            for o in out
        ):
            out.append(m)
    return out


def read_tags(path):
    """Pull existing artist/title tags if present."""
    try:
        f = MutagenFile(path, easy=True)
        if f:
            return {
                "artist": f.get("artist", [""])[0],
                "title": f.get("title", [""])[0],
            }
    except Exception:
        pass
    return {"artist": "", "title": ""}


def analyze_track(path, preset):
    y, sr = load_audio(path)
    duration = librosa.get_duration(y=y, sr=sr)

    camelot, key_name = estimate_key(y, sr)
    bpm = estimate_bpm(y, sr, preset)
    times, norm = energy_curve(y, sr)
    riser = riser_curve(y, sr)
    levels = energy_levels(times, norm)
    markers = detect_structure(times, norm, riser, preset)
    tags = read_tags(path)
    comparison_features, comparison_errors = extract_comparison_features(path, y, sr)

    return {
        "analysis_version": ANALYSIS_VERSION,
        "file": os.path.basename(path),
        "artist": tags["artist"],
        "title": tags["title"],
        "duration_sec": round(duration, 1),
        "bpm": bpm,
        "camelot": camelot,
        "key": key_name,
        "avg_energy_level": int(round(float(norm.mean()) * 9)) + 1,
        "energy_levels": levels,
        "structure_markers": markers,
        "comparison_features": comparison_features,
        "comparison_errors": comparison_errors,
    }


def main():
    ap = argparse.ArgumentParser(description="DJ Set Analyzer")
    ap.add_argument("--input", default="tracks", help="audio folder")
    ap.add_argument("--output", default="output", help="results folder")
    ap.add_argument(
        "--genre", choices=["trance", "techno"], default="techno", help="genre preset"
    )
    args = ap.parse_args()

    preset = PRESETS[args.genre]

    in_dir, out_dir = Path(args.input), Path(args.output)
    out_dir.mkdir(exist_ok=True)

    exts = {".mp3", ".wav", ".flac", ".m4a", ".aiff", ".ogg"}
    files = [p for p in sorted(in_dir.iterdir()) if p.suffix.lower() in exts]
    if not files:
        print(f"No audio files found in {in_dir}/")
        return

    results = []
    for p in tqdm(files, desc="Analyzing"):
        try:
            results.append(analyze_track(str(p), preset))
        except Exception as e:
            print(f"  ! Failed on {p.name}: {e}")

    # JSON (full detail)
    json_path = out_dir / "tracklist_analysis.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)

    # CSV (flat summary)
    csv_path = out_dir / "tracklist_summary.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "file",
                "artist",
                "title",
                "bpm",
                "camelot",
                "key",
                "duration_sec",
                "avg_energy_level",
                "first_drop_sec",
            ]
        )
        for r in results:
            drop = next(
                (m["time"] for m in r["structure_markers"] if m["type"] == "drop"), ""
            )
            w.writerow(
                [
                    r["file"],
                    r["artist"],
                    r["title"],
                    r["bpm"],
                    r["camelot"],
                    r["key"],
                    r["duration_sec"],
                    r["avg_energy_level"],
                    drop,
                ]
            )

    print(f"\nWrote {json_path}\nWrote {csv_path}")


if __name__ == "__main__":
    main()
