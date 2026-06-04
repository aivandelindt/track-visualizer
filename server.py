#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
from email.parser import BytesParser
from email.policy import default
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
ANALYZE_PATH = ROOT / "analyze.py"


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

        self.send_json(
            {
                "tracks": tracks,
                "source": {
                    "folder": folder_name,
                    "genre": genre,
                    "fileCount": len(track_uploads),
                    "command": f"python analyze.py --input <selected-folder> --output <temp-output> --genre {genre}",
                    "log": analyzer_output,
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
