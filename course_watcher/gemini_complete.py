#!/usr/bin/env python3
"""
Complete the course_output for lessons that have no transcript.
Uses Gemini Files API: gets the Wistia stream URL (no local download),
uploads it to Google's servers, then asks Gemini to transcribe + summarize.

Usage:
    GEMINI_API_KEY=... COURSE_EMAIL=... COURSE_PASSWORD=... python gemini_complete.py
"""

import os
import re
import sys
import json
import time
import subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

BASE_URL = "https://www.contentcreator.com"
COURSE_SLUG = "ai-creator-course"
COURSE_ROOT = f"{BASE_URL}/products/{COURSE_SLUG}"
OUTPUT_DIR = Path("course_output")

YT_DLP_CMD = [sys.executable, "-m", "yt_dlp"]
GEMINI_MODEL = "gemini-2.0-flash"


def safe_name(text: str, maxlen: int = 80) -> str:
    return re.sub(r"[^\w\s-]", "_", text)[:maxlen].strip(" _")


def login(email: str, password: str) -> requests.Session:
    print(f"[*] Logging in as {email} ...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    })
    r = session.get(f"{BASE_URL}/login")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    csrf_meta = soup.find("meta", {"name": "csrf-token"})
    csrf_input = soup.find("input", {"name": "authenticity_token"})
    csrf = (csrf_meta["content"] if csrf_meta else None) or (csrf_input["value"] if csrf_input else None)
    if not csrf:
        raise RuntimeError("Cannot find CSRF token")
    r2 = session.post(f"{BASE_URL}/login", data={
        "authenticity_token": csrf,
        "member[email]": email,
        "member[password]": password,
    }, allow_redirects=True)
    if "/login" in r2.url.lower():
        raise RuntimeError("Login failed")
    print(f"[+] Logged in -> {r2.url}")
    return session


def get_wistia_hashes(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    hashes = []
    for div in soup.find_all("div", class_=True):
        for cls in div.get("class", []):
            if cls.startswith("wistia_async_"):
                h = cls.replace("wistia_async_", "").strip()
                if h and h not in hashes:
                    hashes.append(h)
    for script in soup.find_all("script"):
        text = script.string or ""
        for m in re.finditer(r'(?:hashedId|videoHash|wistia)["\s:]*["\']([a-z0-9]{7,14})["\']', text, re.IGNORECASE):
            h = m.group(1)
            if h not in hashes:
                hashes.append(h)
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "wistia" in src.lower():
            m = re.search(r"/medias?/([a-z0-9]+)", src)
            if m and m.group(1) not in hashes:
                hashes.append(m.group(1))
    return hashes


def get_stream_url(hash_id: str, cookie_header: str) -> str | None:
    """Use yt-dlp to get the direct stream URL without downloading."""
    urls = [
        f"https://fast.wistia.net/medias/{hash_id}",
        f"https://home.wistia.com/medias/{hash_id}",
    ]
    for url in urls:
        result = subprocess.run(
            YT_DLP_CMD + [
                "--get-url", "--no-warnings",
                "--add-header", f"Cookie: {cookie_header}",
                "--add-header", f"Referer: {BASE_URL}/",
                url,
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            # May return multiple URLs; take the first MP4
            for line in result.stdout.strip().splitlines():
                if line.startswith("http"):
                    return line.strip()
    return None


def gemini_transcribe_from_url(client: genai.Client, stream_url: str, lesson_title: str) -> str:
    """Upload video URL to Gemini Files API and transcribe."""
    print(f"  [*] Uploading to Gemini Files API ...")
    # Stream download in chunks and upload via bytes (avoids saving full file locally)
    # Gemini Files API accepts a file-like object
    r = requests.get(stream_url, stream=True, timeout=30)
    r.raise_for_status()

    # Write to a small temp file (Gemini needs a seekable stream or path)
    tmp_path = Path("_gemini_tmp_video.mp4")
    written = 0
    with tmp_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
            f.write(chunk)
            written += len(chunk)
            print(f"    downloaded {written // (1024*1024)} MB ...", end="\r")
    print()

    try:
        print(f"  [*] Uploading {written // (1024*1024)} MB to Gemini ...")
        video_file = client.files.upload(file=str(tmp_path), config={"mime_type": "video/mp4"})

        # Wait for processing
        while video_file.state.name == "PROCESSING":
            time.sleep(5)
            video_file = client.files.get(name=video_file.name)

        if video_file.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini file state: {video_file.state.name}")

        print(f"  [*] Asking Gemini to transcribe ...")
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_uri(file_uri=video_file.uri, mime_type="video/mp4"),
                f"This is a lesson titled '{lesson_title}' from an AI Creator Course. "
                "Please provide a detailed transcript of everything spoken in this video, "
                "then a structured summary with key points, tools mentioned, and actionable takeaways. "
                "Format: first a '## Transcript' section, then a '## Key Takeaways' section.",
            ],
        )
        client.files.delete(name=video_file.name)
        return response.text

    finally:
        tmp_path.unlink(missing_ok=True)


def build_master_notes():
    """Regenerate MASTER_NOTES.md from all existing notes.md files."""
    notes_files = sorted(OUTPUT_DIR.glob("*/notes.md"))
    master = OUTPUT_DIR / "MASTER_NOTES.md"
    with master.open("w", encoding="utf-8") as f:
        f.write(f"# AI Creator Course -- Complete Notes\n\n")
        f.write(f"*{len(notes_files)} lessons*\n\n---\n\n")
        for nf in notes_files:
            content = nf.read_text(encoding="utf-8")
            f.write(f"\n\n{content}\n\n---\n")
    print(f"[+] MASTER_NOTES.md written ({len(notes_files)} lessons)")


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: set GEMINI_API_KEY env var")
        sys.exit(1)

    email = os.environ.get("COURSE_EMAIL")
    password = os.environ.get("COURSE_PASSWORD")
    if not email or not password:
        print("Error: set COURSE_EMAIL and COURSE_PASSWORD env vars")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Find lesson dirs missing transcripts
    missing_dirs = [
        d for d in sorted(OUTPUT_DIR.iterdir())
        if d.is_dir() and not list(d.glob("transcript_*.txt"))
    ]
    print(f"[*] {len(missing_dirs)} lessons need Gemini transcription: {[d.name for d in missing_dirs]}")

    if missing_dirs:
        session = login(email, password)
        cookie_header = "; ".join(f"{k}={v}" for k, v in session.cookies.items())

        for lesson_dir in missing_dirs:
            page_html = (lesson_dir / "page.html").read_text(encoding="utf-8", errors="replace")
            title = lesson_dir.name[4:].replace("_", " ")  # strip "NNN_"
            print(f"\n--- {lesson_dir.name}")

            hashes = get_wistia_hashes(page_html)
            if not hashes:
                print(f"  [!] No Wistia hash found in page.html, skipping")
                continue

            for i, h in enumerate(hashes):
                print(f"  [*] Wistia hash: {h}")
                stream_url = get_stream_url(h, cookie_header)
                if not stream_url:
                    print(f"  [!] Could not get stream URL for {h}")
                    continue

                print(f"  [*] Stream URL obtained")
                try:
                    text = gemini_transcribe_from_url(client, stream_url, title)
                    (lesson_dir / f"transcript_wistia_{i}.txt").write_text(text, encoding="utf-8")
                    print(f"  [+] Transcript: {len(text)} chars")

                    # Update notes.md
                    notes_path = lesson_dir / "notes.md"
                    existing = notes_path.read_text(encoding="utf-8") if notes_path.exists() else f"# {title}\n"
                    if "## Full Video Transcript" not in existing:
                        notes_path.write_text(
                            existing.rstrip() + f"\n\n## Full Video Transcript (via Gemini)\n\n{text}\n",
                            encoding="utf-8"
                        )
                except Exception as e:
                    print(f"  [!] Gemini error: {e}")

            time.sleep(2)

    build_master_notes()
    print("\n[+] Done!")


if __name__ == "__main__":
    main()
