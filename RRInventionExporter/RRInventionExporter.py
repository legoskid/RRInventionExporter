import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TeeFile:
    """Write to both a file and another stream (e.g. stdout) simultaneously."""

    def __init__(self, file, stream):
        self.file = file
        self.stream = stream

    def write(self, data):
        self.file.write(data)
        self.stream.write(data)

    def flush(self):
        self.file.flush()
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def sanitize_folder_name(name: str, max_length: int = 50) -> str:
    """Remove characters that are invalid in folder names and truncate."""
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return sanitized[:max_length].strip()


def download_file(url: str, dest_path: str, headers: dict) -> bool:
    """Download a file from a URL to dest_path. Returns True on success."""
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=60, verify=False)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except requests.RequestException as e:
        print(f"  WARNING: Failed to download {url}: {e}")
        return False


def fetch_json(url: str, headers: dict) -> dict | list | None:
    """Fetch JSON from a URL. Returns parsed object or None on failure."""
    try:
        response = requests.get(url, headers=headers, timeout=60, verify=False)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"  WARNING: Request failed for {url}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"  WARNING: Failed to parse JSON from {url}: {e}")
        return None


def main():
    print("=== RRInventionExporter ===\n")

    parser = argparse.ArgumentParser(description="RRInventionExporter")
    parser.add_argument("--token", help="Bearer token for authentication")
    parser.add_argument("--json", dest="json_file", help="Path to the JSON file")
    args = parser.parse_args()

    if args.token:
        bearer_token = args.token.strip()
    else:
        print("Enter your Bearer token: ", end="", flush=True)
        bearer_token = sys.stdin.readline().strip()
    if not bearer_token:
        print("ERROR: Bearer token cannot be empty.")
        sys.exit(1)

    if args.json_file:
        json_file_path = args.json_file.strip().strip('"')
    else:
        json_file_path = input("Enter the path to the JSON file: ").strip().strip('"')
    if not os.path.isfile(json_file_path):
        print(f"ERROR: File not found: {json_file_path}")
        sys.exit(1)

    with open(json_file_path, "r", encoding="utf-8") as f:
        try:
            invention_list = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON file: {e}")
            sys.exit(1)

    if not isinstance(invention_list, list):
        print("ERROR: JSON file must contain a top-level array [].")
        sys.exit(1)

    auth_headers = {"Authorization": f"Bearer {bearer_token}"}

    # Directory containing this script (for locating helper scripts)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # --- Set up logging ---
    original_stdout = sys.stdout
    log_filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = os.path.join(script_dir, log_filename)
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = TeeFile(log_file, original_stdout)

    try:
        total = len(invention_list)
        print(f"Found {total} invention(s) to export.\n")

        for index, invention in enumerate(invention_list, start=1):
            invention_id = invention.get("InventionId")
            name = invention.get("Name", f"Invention_{invention_id}")
            current_version_number = invention.get("CurrentVersionNumber")
            image_name = invention.get("ImageName")
            current_version = invention.get("CurrentVersion", {})
            blob_name = current_version.get("BlobName") if isinstance(current_version, dict) else None

            print(f"[{index}/{total}] Processing: {name} (ID: {invention_id})")

            # --- Create output folder ---
            folder_name = sanitize_folder_name(name)
            folder_path = os.path.join(script_dir, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            print(f"  Folder: {folder_path}")

            # --- Save raw invention JSON ---
            invention_json_path = os.path.join(folder_path, "invention.json")
            with open(invention_json_path, "w", encoding="utf-8") as f:
                json.dump(invention, f, indent=2, ensure_ascii=False)
            print(f"  Saved invention.json")

            # --- HTTP requests ---
            api_results = {}

            print(f"  Fetching version info...")
            version_url = (
                f"https://api.rec.net/api/inventions/v1/version"
                f"?inventionId={invention_id}&version={current_version_number}"
            )
            api_results["version"] = fetch_json(version_url, auth_headers)

            print(f"  Fetching details...")
            details_url = f"https://api.rec.net/api/inventions/v1/details?inventionId={invention_id}"
            api_results["details"] = fetch_json(details_url, auth_headers)

            print(f"  Fetching personal details...")
            personal_url = f"https://api.rec.net/api/inventions/v1/personaldetails/{invention_id}"
            api_results["personaldetails"] = fetch_json(personal_url, auth_headers)

            api_json_path = os.path.join(folder_path, "api_data.json")
            with open(api_json_path, "w", encoding="utf-8") as f:
                json.dump(api_results, f, indent=2, ensure_ascii=False)
            print(f"  Saved api_data.json")

            # --- Download image ---
            if image_name:
                image_url = f"https://img.rec.net/{image_name}"
                image_ext = os.path.splitext(image_name)[1] or ".jpg"
                image_path = os.path.join(folder_path, f"image{image_ext}")
                print(f"  Downloading image: {image_url}")
                download_file(image_url, image_path, auth_headers)
            else:
                print(f"  WARNING: No ImageName found, skipping image download.")

            # --- Download blob ---
            if blob_name:
                blob_url = f"https://cdn.rec.net/invention/{blob_name}"
                blob_path = os.path.join(folder_path, blob_name)
                print(f"  Downloading blob: {blob_url}")
                download_file(blob_url, blob_path, {})

                # --- Run asset downloader scripts ---
                asset_scripts = [
                    "download_htr_assets.py",
                    "download_png_assets.py",
                    "download_jpg_assets.py",
                ]
                for script_name in asset_scripts:
                    script_path = os.path.join(script_dir, script_name)
                    if not os.path.isfile(script_path):
                        print(f"  WARNING: Script not found, skipping: {script_path}")
                        continue
                    print(blob_path)
                    cmd = [sys.executable, script_path, blob_path, "-o", folder_path]
                    print(f"  Running: {script_name} ...")
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True)
                        if result.stdout:
                            print(result.stdout, end='')
                        if result.stderr:
                            print(result.stderr, end='')
                        if result.returncode != 0:
                            print(f"  ERROR: Script {script_name} exited with code {result.returncode}")
                        else:
                            print(f"    Done.")
                    except Exception as e:
                        print(f"    ERROR running {script_name}: {e}")
            else:
                print(f"  WARNING: No BlobName found in CurrentVersion, skipping blob download and asset scripts.")

            print()

        print("=== Export complete! ===")

    finally:
        sys.stdout = original_stdout
        log_file.close()
        print(f"Log saved to: {log_path}")


if __name__ == "__main__":
    main()
