#!/usr/bin/env python3

import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from tinydb import Query, TinyDB

ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
ANALYZE_PATH = ROOT / "analyze.py"
TRACKS_PATH = ROOT / "output" / "tracklist_analysis.json"
FALLBACK_TRACKS_PATH = ROOT / "output" / "tracklist_analysis example.json"
TINYDB_PATH = ROOT / "output" / "track_cache.json"

FILTER_IDS = {"all", "high-energy", "trancey", "slow-burn"}
MAX_SIMILAR_LIMIT = 50
MAX_PLAYLIST_LIMIT = 25

DJ_TRANSITION_THRESHOLDS = {
    "straight_mix_bpm_delta": 2.0,
    "small_nudge_bpm_delta": 6.0,
    "tempo_risk_bpm_delta": 10.0,
    "energy_shift_delta": 1.5,
    "energy_risk_delta": 3.0,
}

MASTERING_THRESHOLDS = {
    "target_lufs": -14.0,
    "lufs_pass_delta": 1.5,
    "lufs_warn_delta": 3.0,
    "crest_min_db": 6.0,
    "crest_warn_db": 4.5,
    "clipping_warn_ratio": 0.001,
    "clipping_fail_ratio": 0.005,
    "brightness_pass_delta_hz": 250.0,
    "brightness_warn_delta_hz": 600.0,
}

DB = TinyDB(TINYDB_PATH)
TRACKS_TABLE = DB.table("tracks")
META_TABLE = DB.table("meta")


def parse_form_data(content_type, body):
    envelope = (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode(
        "utf-8"
    )
    message = BytesParser(policy=default).parsebytes(envelope + body)

    fields = {}
    uploads = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue

        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""

        if filename:
            uploads.append(
                {
                    "field": name,
                    "filename": filename,
                    "content": payload,
                }
            )
            continue

        charset = part.get_content_charset() or "utf-8"
        fields[name] = payload.decode(charset, errors="replace")

    return fields, uploads


def normalize_upload_name(filename):
    path = PurePosixPath(filename)
    clean_parts = [part for part in path.parts if part not in {"", "."}]
    if not clean_parts or any(part == ".." for part in clean_parts):
        raise ValueError(f"Invalid upload path: {filename}")

    folder_name = clean_parts[0] if len(clean_parts) > 1 else "Selected Folder"
    file_name = clean_parts[-1]
    return folder_name, file_name


def write_uploads(input_dir, uploads):
    folder_name = "Selected Folder"
    used_names = set()

    for upload in uploads:
        current_folder, file_name = normalize_upload_name(upload["filename"])
        folder_name = current_folder or folder_name

        candidate = Path(file_name)
        stem = candidate.stem
        suffix = candidate.suffix
        dedupe = 1
        while candidate.name in used_names:
            candidate = Path(f"{stem}-{dedupe}{suffix}")
            dedupe += 1

        used_names.add(candidate.name)
        destination = input_dir / candidate.name
        destination.write_bytes(upload["content"])

    return folder_name


def run_analysis(input_dir, output_dir, genre):
    command = [
        sys.executable,
        str(ANALYZE_PATH),
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--genre",
        genre,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            (completed.stderr or completed.stdout).strip() or "Analysis failed."
        )

    result_path = output_dir / "tracklist_analysis.json"
    if not result_path.exists():
        raise RuntimeError("Analyzer did not produce tracklist_analysis.json.")

    return json.loads(result_path.read_text()), completed.stdout.strip()


def _safe_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _track_search_blob(track):
    fields = [
        str(track.get("artist", "")),
        str(track.get("title", "")),
        str(track.get("key", "")),
        str(track.get("camelot", "")),
        str(track.get("file", "")),
        str(track.get("bpm", "")),
    ]
    return " ".join(fields).lower()


def _enrich_track(track):
    enriched = dict(track)
    enriched["bpm"] = _safe_number(track.get("bpm"))
    enriched["avg_energy_level"] = _safe_int(track.get("avg_energy_level"))
    enriched["duration_sec"] = _safe_number(track.get("duration_sec"))
    enriched["_search_blob"] = _track_search_blob(track)
    return enriched


def _sanitize_track(track):
    clean = dict(track)
    clean.pop("_search_blob", None)
    return clean


def _analysis_version_number(track):
    return _safe_float(track.get("analysis_version"), default=0.0)


def _comparison_feature_completeness(track):
    features = _comparison_features(track)
    metric_keys = [
        "lufs",
        "lra_lu",
        "crest_factor_db",
        "spectral_centroid_hz",
        "bass_ratio",
        "mid_ratio",
        "high_ratio",
    ]

    score = 0
    for key in metric_keys:
        value = features.get(key)
        if value is None:
            continue
        number = _safe_float(value, default=float("nan"))
        if math.isfinite(number):
            score += 1

    return score


def _pick_best_track_variant(tracks):
    if not tracks:
        return None

    def rank(track):
        return (
            _comparison_feature_completeness(track),
            _analysis_version_number(track),
        )

    return max(tracks, key=rank)


def _dedupe_tracks_by_file(tracks):
    grouped = {}
    order = []

    for track in tracks:
        file_name = str(track.get("file", "")).strip()
        if file_name not in grouped:
            grouped[file_name] = []
            order.append(file_name)
        grouped[file_name].append(track)

    deduped = []
    for file_name in order:
        best = _pick_best_track_variant(grouped[file_name])
        if best is not None:
            deduped.append(best)
    return deduped


def load_tracks_from_disk():
    source_path = TRACKS_PATH if TRACKS_PATH.exists() else FALLBACK_TRACKS_PATH
    if not source_path.exists():
        raise RuntimeError("No bundled analysis JSON was found in output/.")

    payload = json.loads(source_path.read_text())
    if not isinstance(payload, list):
        raise RuntimeError(f"Expected a JSON array in {source_path.name}.")

    return payload, source_path.name


def replace_tracks_in_db(tracks, *, folder, genre, mode, label):
    TRACKS_TABLE.truncate()

    if tracks:
        TRACKS_TABLE.insert_multiple([_enrich_track(track) for track in tracks])

    META_TABLE.truncate()
    META_TABLE.insert(
        {
            "folder": folder,
            "genre": genre,
            "mode": mode,
            "label": label,
            "fileCount": len(tracks),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


def get_source_metadata():
    return (
        META_TABLE.all()[0]
        if len(META_TABLE) > 0
        else {
            "folder": "Bundled sample JSON",
            "genre": "trance",
            "mode": "sample",
            "label": TRACKS_PATH.name,
            "fileCount": len(TRACKS_TABLE),
        }
    )


def ensure_seed_data():
    if len(TRACKS_TABLE) > 0:
        return

    tracks, source_name = load_tracks_from_disk()
    replace_tracks_in_db(
        tracks,
        folder="Bundled sample JSON",
        genre="trance",
        mode="sample",
        label=source_name,
    )


def query_tracks(search="", filter_id="all"):
    ensure_seed_data()

    track_query = Query()
    combined_query = None

    normalized_search = str(search or "").strip().lower()
    if normalized_search:
        escaped = re.escape(normalized_search)
        combined_query = track_query._search_blob.search(escaped)

    normalized_filter = filter_id if filter_id in FILTER_IDS else "all"
    filter_query = None
    if normalized_filter == "high-energy":
        filter_query = track_query.avg_energy_level >= 8
    elif normalized_filter == "trancey":
        filter_query = (track_query.bpm >= 128) & (track_query.bpm <= 145)
    elif normalized_filter == "slow-burn":
        filter_query = track_query.bpm < 100

    if filter_query is not None:
        combined_query = (
            filter_query if combined_query is None else (combined_query & filter_query)
        )

    records = (
        TRACKS_TABLE.search(combined_query)
        if combined_query is not None
        else TRACKS_TABLE.all()
    )
    tracks = [_sanitize_track(record) for record in records]
    tracks = _dedupe_tracks_by_file(tracks)
    tracks.sort(
        key=lambda track: (
            str(track.get("artist", "")).lower(),
            str(track.get("title", "")).lower(),
        )
    )
    return tracks


def _safe_float(value, default=0.0):
    try:
        number = float(value)
        if not math.isfinite(number):
            return float(default)
        return number
    except (TypeError, ValueError):
        return float(default)


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def _norm_range(value, low, high, default=0.0):
    if high <= low:
        return float(default)
    number = _safe_float(value, default=default)
    return _clamp01((number - low) / (high - low))


def _camelot_parts(camelot):
    text = str(camelot or "").strip().upper()
    match = re.match(r"^(1[0-2]|[1-9])([AB])$", text)
    if not match:
        return None
    number = int(match.group(1))
    mode = match.group(2)
    return number, mode


def _camelot_distance_score(left_camelot, right_camelot):
    left = _camelot_parts(left_camelot)
    right = _camelot_parts(right_camelot)
    if not left or not right:
        return 0.3

    lnum, lmode = left
    rnum, rmode = right

    if lnum == rnum and lmode == rmode:
        return 1.0
    if lnum == rnum and lmode != rmode:
        return 0.82

    clockwise = (lnum % 12) + 1
    counter = ((lnum + 10) % 12) + 1
    if rmode == lmode and rnum in {clockwise, counter}:
        return 0.9

    return 0.2


def _comparison_features(track):
    features = track.get("comparison_features")
    return features if isinstance(features, dict) else {}


def _mfcc_vector(track):
    features = _comparison_features(track)
    mean = features.get("mfcc_mean") or []
    std = features.get("mfcc_std") or []

    padded = []
    for value in list(mean)[:13] + [0.0] * max(0, 13 - len(mean)):
        padded.append(_safe_float(value, default=0.0))
    for value in list(std)[:13] + [0.0] * max(0, 13 - len(std)):
        padded.append(_safe_float(value, default=0.0))
    return padded


def _scalar_feature_vector(track):
    features = _comparison_features(track)
    vector = [
        _norm_range(features.get("spectral_centroid_hz"), 0.0, 8000.0),
        _norm_range(features.get("bass_ratio"), 0.0, 1.0),
        _norm_range(features.get("mid_ratio"), 0.0, 1.0),
        _norm_range(features.get("high_ratio"), 0.0, 1.0),
        _norm_range(features.get("lufs"), -45.0, 0.0),
        _norm_range(features.get("lra_lu"), 0.0, 25.0),
        _norm_range(features.get("crest_factor_db"), 0.0, 25.0),
        _norm_range(features.get("stereo_width"), 0.0, 2.0),
        _norm_range(features.get("clipping_ratio"), 0.0, 0.05),
        _norm_range(features.get("transient_sharpness"), 0.0, 12.0),
    ]
    return [0.0 if not math.isfinite(v) else float(v) for v in vector]


def _comparison_vector(track):
    vector = _mfcc_vector(track) + _scalar_feature_vector(track)
    clean = []
    for value in vector:
        number = _safe_float(value, default=0.0)
        clean.append(0.0 if not math.isfinite(number) else number)
    return clean


def _cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(left_value * left_value for left_value in left))
    right_norm = math.sqrt(sum(right_value * right_value for right_value in right))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return 0.0
    cosine = dot / (left_norm * right_norm)
    return _clamp01((cosine + 1.0) * 0.5)


def _spectral_similarity_score(left_track, right_track):
    left_features = _comparison_features(left_track)
    right_features = _comparison_features(right_track)
    left = [
        _safe_float(left_features.get("bass_ratio")),
        _safe_float(left_features.get("mid_ratio")),
        _safe_float(left_features.get("high_ratio")),
    ]
    right = [
        _safe_float(right_features.get("bass_ratio")),
        _safe_float(right_features.get("mid_ratio")),
        _safe_float(right_features.get("high_ratio")),
    ]
    distance = math.sqrt(
        sum(
            (left_value - right_value) ** 2
            for left_value, right_value in zip(left, right)
        )
    )
    max_distance = math.sqrt(3.0)
    return _clamp01(1.0 - (distance / max_distance))


def _tempo_similarity_score(left_track, right_track):
    left_bpm = _safe_float(left_track.get("bpm"), default=0.0)
    right_bpm = _safe_float(right_track.get("bpm"), default=0.0)
    if left_bpm <= 0.0 or right_bpm <= 0.0:
        return 0.0
    bpm_delta = abs(left_bpm - right_bpm)
    return _clamp01(1.0 - (bpm_delta / 25.0))


def _bpm_transition_recommendation(left_track, right_track):
    thresholds = dict(DJ_TRANSITION_THRESHOLDS)
    bpm_delta = abs(
        _safe_float(left_track.get("bpm"), default=0.0)
        - _safe_float(right_track.get("bpm"), default=0.0)
    )

    if bpm_delta <= thresholds["straight_mix_bpm_delta"]:
        recommendation = "straight mix"
        tag = "tempo-safe"
    elif bpm_delta <= thresholds["small_nudge_bpm_delta"]:
        recommendation = "small nudge"
        tag = "tempo-nudge"
    else:
        recommendation = "risky"
        tag = "tempo-risk"

    return {
        "recommendation": recommendation,
        "bpm_delta": round(bpm_delta, 3),
        "thresholds": {
            "straight_mix_max_delta": thresholds["straight_mix_bpm_delta"],
            "small_nudge_max_delta": thresholds["small_nudge_bpm_delta"],
            "tempo_risk_min_delta": thresholds["tempo_risk_bpm_delta"],
        },
        "tag": tag,
    }


def _energy_transition_profile(left_track, right_track):
    thresholds = dict(DJ_TRANSITION_THRESHOLDS)
    left_energy = _safe_float(left_track.get("avg_energy_level"), default=0.0)
    right_energy = _safe_float(right_track.get("avg_energy_level"), default=0.0)
    delta = abs(right_energy - left_energy)

    if delta <= thresholds["energy_shift_delta"]:
        classification = "steady"
        tag = "energy-steady"
    elif delta <= thresholds["energy_risk_delta"]:
        classification = "energy-shift"
        tag = "energy-shift"
    else:
        classification = "energy-risk"
        tag = "energy-risk"

    direction = "flat"
    if right_energy > left_energy:
        direction = "up"
    elif right_energy < left_energy:
        direction = "down"

    return {
        "classification": classification,
        "direction": direction,
        "energy_delta": round(delta, 3),
        "thresholds": {
            "energy_shift_max_delta": thresholds["energy_shift_delta"],
            "energy_risk_min_delta": thresholds["energy_risk_delta"],
        },
        "tag": tag,
    }


def _harmonic_transition_profile(left_track, right_track):
    score = _camelot_distance_score(
        left_track.get("camelot"), right_track.get("camelot")
    )
    compatible = score >= 0.82
    if score >= 0.9:
        relation = "neighbor-compatible"
    elif score >= 0.82:
        relation = "relative-compatible"
    elif score >= 0.5:
        relation = "workable"
    else:
        relation = "off-lane"

    return {
        "compatible": compatible,
        "score": round(score, 4),
        "relation": relation,
        "tag": "harmonic" if compatible else "harmonic-risk",
    }


def _dj_workflow_profile(left_track, right_track):
    harmonic = _harmonic_transition_profile(left_track, right_track)
    bpm_transition = _bpm_transition_recommendation(left_track, right_track)
    energy_transition = _energy_transition_profile(left_track, right_track)

    tags = []
    for tag in [
        harmonic.get("tag"),
        energy_transition.get("tag"),
        bpm_transition.get("tag"),
    ]:
        if tag and tag not in tags:
            tags.append(tag)

    return {
        "harmonic_mix": harmonic.get("compatible", False),
        "harmonic": harmonic,
        "bpm_transition": bpm_transition,
        "energy_transition": energy_transition,
        "tags": tags,
    }


def _loudness_dynamics_score(left_track, right_track):
    left = _comparison_features(left_track)
    right = _comparison_features(right_track)

    lufs_delta = abs(_safe_float(left.get("lufs")) - _safe_float(right.get("lufs")))
    lra_delta = abs(_safe_float(left.get("lra_lu")) - _safe_float(right.get("lra_lu")))
    crest_delta = abs(
        _safe_float(left.get("crest_factor_db"))
        - _safe_float(right.get("crest_factor_db"))
    )
    clip_delta = abs(
        _safe_float(left.get("clipping_ratio"))
        - _safe_float(right.get("clipping_ratio"))
    )

    penalties = [
        _clamp01(lufs_delta / 10.0),
        _clamp01(lra_delta / 8.0),
        _clamp01(crest_delta / 8.0),
        _clamp01(clip_delta / 0.02),
    ]
    return _clamp01(1.0 - (sum(penalties) / len(penalties)))


def _track_identity(track):
    return {
        "file": str(track.get("file", "")),
        "artist": str(track.get("artist", "")),
        "title": str(track.get("title", "")),
        "bpm": _safe_float(track.get("bpm"), default=0.0),
        "camelot": str(track.get("camelot", "")),
    }


def _status_from_delta(value, pass_limit, warn_limit):
    number = abs(_safe_float(value, default=0.0))
    if number <= pass_limit:
        return "pass"
    if number <= warn_limit:
        return "warn"
    return "fail"


def _status_from_floor(value, pass_floor, warn_floor):
    number = _safe_float(value, default=0.0)
    if number >= pass_floor:
        return "pass"
    if number >= warn_floor:
        return "warn"
    return "fail"


def _status_from_ceiling(value, pass_ceiling, warn_ceiling):
    number = _safe_float(value, default=0.0)
    if number <= pass_ceiling:
        return "pass"
    if number <= warn_ceiling:
        return "warn"
    return "fail"


def _mastering_assessment(left_track, right_track, deltas):
    thresholds = dict(MASTERING_THRESHOLDS)
    left_features = _comparison_features(left_track)
    right_features = _comparison_features(right_track)

    left_lufs = _safe_float(left_features.get("lufs"))
    right_lufs = _safe_float(right_features.get("lufs"))
    left_crest = _safe_float(left_features.get("crest_factor_db"))
    right_crest = _safe_float(right_features.get("crest_factor_db"))
    left_clip = _safe_float(left_features.get("clipping_ratio"))
    right_clip = _safe_float(right_features.get("clipping_ratio"))

    loudness_alignment = _status_from_delta(
        deltas.get("lufs"),
        pass_limit=thresholds["lufs_pass_delta"],
        warn_limit=thresholds["lufs_warn_delta"],
    )
    brightness_alignment = _status_from_delta(
        deltas.get("spectral_centroid_hz"),
        pass_limit=thresholds["brightness_pass_delta_hz"],
        warn_limit=thresholds["brightness_warn_delta_hz"],
    )
    left_lufs_target = _status_from_delta(
        left_lufs - thresholds["target_lufs"],
        pass_limit=thresholds["lufs_pass_delta"],
        warn_limit=thresholds["lufs_warn_delta"],
    )
    right_lufs_target = _status_from_delta(
        right_lufs - thresholds["target_lufs"],
        pass_limit=thresholds["lufs_pass_delta"],
        warn_limit=thresholds["lufs_warn_delta"],
    )
    dynamics_left = _status_from_floor(
        left_crest,
        pass_floor=thresholds["crest_min_db"],
        warn_floor=thresholds["crest_warn_db"],
    )
    dynamics_right = _status_from_floor(
        right_crest,
        pass_floor=thresholds["crest_min_db"],
        warn_floor=thresholds["crest_warn_db"],
    )
    clipping_left = _status_from_ceiling(
        left_clip,
        pass_ceiling=thresholds["clipping_warn_ratio"],
        warn_ceiling=thresholds["clipping_fail_ratio"],
    )
    clipping_right = _status_from_ceiling(
        right_clip,
        pass_ceiling=thresholds["clipping_warn_ratio"],
        warn_ceiling=thresholds["clipping_fail_ratio"],
    )

    flags = {
        "loudness_alignment": loudness_alignment,
        "brightness_alignment": brightness_alignment,
        "left_lufs_target": left_lufs_target,
        "right_lufs_target": right_lufs_target,
        "left_dynamics": dynamics_left,
        "right_dynamics": dynamics_right,
        "left_clipping": clipping_left,
        "right_clipping": clipping_right,
    }

    recommendations = []
    if loudness_alignment != "pass":
        recommendations.append(
            "Align integrated loudness before final compare; target similar LUFS envelopes."
        )
    if brightness_alignment == "fail":
        recommendations.append(
            "Spectral brightness gap is large; rebalance high-end EQ before transition."
        )
    if dynamics_left != "pass" or dynamics_right != "pass":
        recommendations.append(
            "Crest factor suggests compression mismatch; revisit bus compression or limiter settings."
        )
    if clipping_left != "pass" or clipping_right != "pass":
        recommendations.append(
            "Clipping risk detected; reduce limiter ceiling or gain stage to preserve headroom."
        )
    if not recommendations:
        recommendations.append(
            "Mastering metrics are aligned; this pair is suitable as a consistent reference transition."
        )

    fail_count = sum(1 for status in flags.values() if status == "fail")
    warn_count = sum(1 for status in flags.values() if status == "warn")
    overall = "fail" if fail_count > 0 else "warn" if warn_count > 0 else "pass"

    return {
        "overall": overall,
        "thresholds": thresholds,
        "flags": flags,
        "recommendations": recommendations,
    }


def _find_track_by_file(file_name):
    if not str(file_name or "").strip():
        raise ValueError("Parameter 'file' is required.")

    ensure_seed_data()
    target = str(file_name).strip()

    matches = []
    for record in TRACKS_TABLE.all():
        if str(record.get("file", "")) == target:
            matches.append(_sanitize_track(record))

    return _pick_best_track_variant(matches)


def _compare_tracks(left_track, right_track):
    left_vector = _comparison_vector(left_track)
    right_vector = _comparison_vector(right_track)

    # These weights sum to 1.0 and keep harmonic/tempo context meaningful for DJs.
    timbre_score = _cosine_similarity(
        _mfcc_vector(left_track), _mfcc_vector(right_track)
    )
    spectral_score = _spectral_similarity_score(left_track, right_track)
    tempo_score = _tempo_similarity_score(left_track, right_track)
    key_score = _camelot_distance_score(
        left_track.get("camelot"), right_track.get("camelot")
    )
    loudness_score = _loudness_dynamics_score(left_track, right_track)

    weighted = (
        (0.35 * timbre_score)
        + (0.20 * spectral_score)
        + (0.20 * tempo_score)
        + (0.15 * key_score)
        + (0.10 * loudness_score)
    )
    similarity_score = round(weighted * 100.0, 2)

    left_features = _comparison_features(left_track)
    right_features = _comparison_features(right_track)

    deltas = {
        "bpm": round(
            abs(
                _safe_float(left_track.get("bpm")) - _safe_float(right_track.get("bpm"))
            ),
            3,
        ),
        "lufs": round(
            abs(
                _safe_float(left_features.get("lufs"))
                - _safe_float(right_features.get("lufs"))
            ),
            3,
        ),
        "lra_lu": round(
            abs(
                _safe_float(left_features.get("lra_lu"))
                - _safe_float(right_features.get("lra_lu"))
            ),
            3,
        ),
        "crest_factor_db": round(
            abs(
                _safe_float(left_features.get("crest_factor_db"))
                - _safe_float(right_features.get("crest_factor_db"))
            ),
            3,
        ),
        "spectral_centroid_hz": round(
            abs(
                _safe_float(left_features.get("spectral_centroid_hz"))
                - _safe_float(right_features.get("spectral_centroid_hz"))
            ),
            3,
        ),
    }

    tags = []
    if key_score >= 0.82:
        tags.append("harmonic")
    if tempo_score >= 0.85:
        tags.append("tempo-safe")
    if spectral_score >= 0.75:
        tags.append("spectral-match")
    if loudness_score < 0.5:
        tags.append("loudness-mismatch")

    dj_workflow = _dj_workflow_profile(left_track, right_track)
    for dj_tag in dj_workflow.get("tags", []):
        if dj_tag not in tags:
            tags.append(dj_tag)

    components = {
        "timbre": round(timbre_score, 4),
        "spectral": round(spectral_score, 4),
        "tempo": round(tempo_score, 4),
        "key": round(key_score, 4),
        "loudness_dynamics": round(loudness_score, 4),
    }

    mastering = _mastering_assessment(left_track, right_track, deltas)

    return {
        "similarity_score": similarity_score,
        "components": components,
        "deltas": deltas,
        "tags": tags,
        "dj_workflow": dj_workflow,
        "mastering": mastering,
        "vector_stats": {
            "left_length": len(left_vector),
            "right_length": len(right_vector),
            "left_has_nan": any(not math.isfinite(v) for v in left_vector),
            "right_has_nan": any(not math.isfinite(v) for v in right_vector),
        },
    }


def compare_tracks_by_file(left_file, right_file):
    left_track = _find_track_by_file(left_file)
    if left_track is None:
        raise ValueError(f"Unknown left track: {left_file}")

    right_track = _find_track_by_file(right_file)
    if right_track is None:
        raise ValueError(f"Unknown right track: {right_file}")

    result = _compare_tracks(left_track, right_track)
    return {
        "left": _track_identity(left_track),
        "right": _track_identity(right_track),
        "left_features": _comparison_features(left_track),
        "right_features": _comparison_features(right_track),
        **result,
    }


def similar_tracks_for_file(file_name, limit=10):
    base_track = _find_track_by_file(file_name)
    if base_track is None:
        raise ValueError(f"Unknown track: {file_name}")

    ensure_seed_data()
    candidates = []
    for record in TRACKS_TABLE.all():
        candidate = _sanitize_track(record)
        if str(candidate.get("file", "")) == str(base_track.get("file", "")):
            continue

        compared = _compare_tracks(base_track, candidate)
        candidates.append(
            {
                "track": _track_identity(candidate),
                "similarity_score": compared["similarity_score"],
                "components": compared["components"],
                "tags": compared["tags"],
                "dj_workflow": compared["dj_workflow"],
            }
        )

    candidates.sort(
        key=lambda item: (
            -_safe_float(item.get("similarity_score"), default=0.0),
            str(item.get("track", {}).get("artist", "")).lower(),
            str(item.get("track", {}).get("title", "")).lower(),
        )
    )
    return {
        "source": _track_identity(base_track),
        "results": candidates[:limit],
    }


def _playlist_transition_score(current_track, candidate_track, compared_payload):
    dj = compared_payload.get("dj_workflow", {})
    bpm_transition = dj.get("bpm_transition", {})
    energy_transition = dj.get("energy_transition", {})

    bpm_delta = _safe_float(bpm_transition.get("bpm_delta"), default=0.0)
    energy_delta = _safe_float(energy_transition.get("energy_delta"), default=0.0)
    similarity = (
        _safe_float(compared_payload.get("similarity_score"), default=0.0) / 100.0
    )

    bpm_penalty = _clamp01(bpm_delta / 12.0)
    energy_penalty = _clamp01(energy_delta / 4.0)
    transition_safety = _clamp01(1.0 - ((0.6 * bpm_penalty) + (0.4 * energy_penalty)))

    score = (0.62 * similarity) + (0.38 * transition_safety)

    if "tempo-risk" in dj.get("tags", []):
        score -= 0.12
    if "energy-risk" in dj.get("tags", []):
        score -= 0.09
    if not dj.get("harmonic_mix"):
        score -= 0.05

    hard_jump = bpm_delta > 10.0 or energy_delta > 3.0
    if hard_jump:
        score -= 0.12

    return {
        "score": round(score, 5),
        "hard_jump": hard_jump,
    }


def playlist_seed_for_file(file_name, limit=8):
    seed_track = _find_track_by_file(file_name)
    if seed_track is None:
        raise ValueError(f"Unknown track: {file_name}")

    ensure_seed_data()
    remaining = []
    for record in TRACKS_TABLE.all():
        candidate = _sanitize_track(record)
        if str(candidate.get("file", "")) == str(seed_track.get("file", "")):
            continue
        remaining.append(candidate)

    ordered_tracks = [_track_identity(seed_track)]
    transitions = []
    current_track = seed_track
    used_files = {str(seed_track.get("file", ""))}

    while len(ordered_tracks) < limit and remaining:
        scored = []
        for candidate in remaining:
            candidate_file = str(candidate.get("file", ""))
            if candidate_file in used_files:
                continue

            compared = _compare_tracks(current_track, candidate)
            ranking = _playlist_transition_score(current_track, candidate, compared)
            scored.append(
                {
                    "candidate": candidate,
                    "compared": compared,
                    "ranking": ranking,
                }
            )

        if not scored:
            break

        scored.sort(
            key=lambda item: (
                item["ranking"]["hard_jump"],
                -_safe_float(item["ranking"]["score"], default=0.0),
                -_safe_float(item["compared"].get("similarity_score"), default=0.0),
                str(item["candidate"].get("artist", "")).lower(),
                str(item["candidate"].get("title", "")).lower(),
            )
        )

        winner = scored[0]
        chosen_track = winner["candidate"]
        chosen_identity = _track_identity(chosen_track)
        ordered_tracks.append(chosen_identity)
        transitions.append(
            {
                "from": _track_identity(current_track),
                "to": chosen_identity,
                "similarity_score": winner["compared"].get("similarity_score"),
                "components": winner["compared"].get("components"),
                "dj_workflow": winner["compared"].get("dj_workflow"),
                "tags": winner["compared"].get("tags", []),
                "ranking": winner["ranking"],
            }
        )

        current_track = chosen_track
        used_files.add(str(chosen_track.get("file", "")))

    return {
        "source": _track_identity(seed_track),
        "playlist": ordered_tracks,
        "transitions": transitions,
    }


class AnalyzerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if urlparse(self.path).path != "/api/analyze":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            self.handle_analyze()
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, status=500)
        except Exception as error:
            self.send_json({"error": f"Unexpected server error: {error}"}, status=500)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/tracks":
            try:
                self.handle_tracks_query(parsed.query)
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json(
                    {"error": f"Unexpected server error: {error}"},
                    status=500,
                )
            return

        if parsed.path == "/api/compare":
            try:
                self.handle_compare_query(parsed.query)
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json(
                    {"error": f"Unexpected server error: {error}"},
                    status=500,
                )
            return

        if parsed.path == "/api/similar":
            try:
                self.handle_similar_query(parsed.query)
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json(
                    {"error": f"Unexpected server error: {error}"},
                    status=500,
                )
            return

        if parsed.path == "/api/playlist-seed":
            try:
                self.handle_playlist_seed_query(parsed.query)
            except ValueError as error:
                self.send_json({"error": str(error)}, status=400)
            except Exception as error:
                self.send_json(
                    {"error": f"Unexpected server error: {error}"},
                    status=500,
                )
            return

        super().do_GET()

    def handle_analyze(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Expected multipart/form-data upload.")

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Empty upload.")

        body = self.rfile.read(content_length)
        fields, uploads = parse_form_data(content_type, body)
        track_uploads = [upload for upload in uploads if upload["field"] == "tracks"]
        if not track_uploads:
            raise ValueError(
                "Select a folder with audio files before running analysis."
            )

        genre = fields.get("genre", "trance").strip().lower() or "trance"
        if genre not in {"trance", "techno"}:
            raise ValueError(f"Unsupported genre preset: {genre}")

        with tempfile.TemporaryDirectory(prefix="dj-analyzer-") as temp_dir:
            temp_root = Path(temp_dir)
            input_dir = temp_root / "input"
            output_dir = temp_root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            folder_name = write_uploads(input_dir, track_uploads)
            tracks, analyzer_output = run_analysis(input_dir, output_dir, genre)

        replace_tracks_in_db(
            tracks,
            folder=folder_name,
            genre=genre,
            mode="uploaded",
            label="/api/analyze",
        )

        self.send_json(
            {
                "tracks": tracks,
                "source": {
                    "folder": folder_name,
                    "genre": genre,
                    "fileCount": len(track_uploads),
                    "command": f"python analyze.py --input <selected-folder> --output <temp-output> --genre {genre}",
                    "log": analyzer_output,
                    "mode": "uploaded",
                },
            }
        )

    def handle_tracks_query(self, query_string):
        query_params = parse_qs(query_string)
        search = query_params.get("search", [""])[0]
        filter_id = query_params.get("filter", ["all"])[0]

        if filter_id not in FILTER_IDS:
            raise ValueError(f"Unsupported filter: {filter_id}")

        tracks = query_tracks(search=search, filter_id=filter_id)
        source = get_source_metadata()
        source["fileCount"] = len(TRACKS_TABLE)

        self.send_json(
            {
                "tracks": tracks,
                "source": source,
                "query": {
                    "search": search,
                    "filter": filter_id,
                },
            }
        )

    def handle_compare_query(self, query_string):
        query_params = parse_qs(query_string)
        left_file = query_params.get("left", [""])[0]
        right_file = query_params.get("right", [""])[0]

        if not left_file:
            raise ValueError("Parameter 'left' is required.")
        if not right_file:
            raise ValueError("Parameter 'right' is required.")

        compared = compare_tracks_by_file(left_file=left_file, right_file=right_file)
        self.send_json(
            {
                **compared,
                "query": {
                    "left": left_file,
                    "right": right_file,
                },
            }
        )

    def handle_similar_query(self, query_string):
        query_params = parse_qs(query_string)
        file_name = query_params.get("file", [""])[0]
        limit_raw = query_params.get("limit", ["10"])[0]

        if not file_name:
            raise ValueError("Parameter 'file' is required.")

        try:
            limit = int(limit_raw)
        except ValueError:
            raise ValueError("Parameter 'limit' must be an integer.") from None

        if limit < 1:
            raise ValueError("Parameter 'limit' must be >= 1.")
        if limit > MAX_SIMILAR_LIMIT:
            raise ValueError(f"Parameter 'limit' must be <= {MAX_SIMILAR_LIMIT}.")

        payload = similar_tracks_for_file(file_name=file_name, limit=limit)
        self.send_json(
            {
                **payload,
                "query": {
                    "file": file_name,
                    "limit": limit,
                },
            }
        )

    def handle_playlist_seed_query(self, query_string):
        query_params = parse_qs(query_string)
        file_name = query_params.get("file", [""])[0]
        limit_raw = query_params.get("limit", ["8"])[0]

        if not file_name:
            raise ValueError("Parameter 'file' is required.")

        try:
            limit = int(limit_raw)
        except ValueError:
            raise ValueError("Parameter 'limit' must be an integer.") from None

        if limit < 2:
            raise ValueError("Parameter 'limit' must be >= 2.")
        if limit > MAX_PLAYLIST_LIMIT:
            raise ValueError(f"Parameter 'limit' must be <= {MAX_PLAYLIST_LIMIT}.")

        payload = playlist_seed_for_file(file_name=file_name, limit=limit)
        self.send_json(
            {
                **payload,
                "query": {
                    "file": file_name,
                    "limit": limit,
                },
            }
        )

    def send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), AnalyzerHandler)
    print(f"Serving visualizer on http://{DEFAULT_HOST}:{DEFAULT_PORT}/index.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
