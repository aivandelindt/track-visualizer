#!/usr/bin/env python3

import json
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
    tracks.sort(
        key=lambda track: (
            str(track.get("artist", "")).lower(),
            str(track.get("title", "")).lower(),
        )
    )
    return tracks


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
