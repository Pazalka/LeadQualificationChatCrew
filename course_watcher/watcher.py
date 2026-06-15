#!/usr/bin/env python3
"""
Course Watcher for contentcreator.com (Kajabi platform)

Logs in, walks every lesson, downloads videos, transcribes them via Whisper,
and writes detailed structured notes to MASTER_NOTES.md.

Usage:
    python watcher.py --email you@example.com --password yourpass
    COURSE_EMAIL=you@example.com COURSE_PASSWORD=pass python watcher.py
"""

import os
import re
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.contentcreator.com"
COURSE_SLUG = "ai-creator-course"
COURSE_ROOT = f"{BASE_URL}/products/{COURSE_SLUG}"


# ─── helpers ────────────────────────────────────────────────────────────────

def safe_name(text: str, maxlen: int = 80) -> str:
    return re.sub(r"[^\w\s-]", "_", text)[:maxlen].strip(" _")


def extract_wistia_hashes(soup: BeautifulSoup) -> list[str]:
    hashes = []

    # <div class="wistia_embed wistia_async_HASH ...">
    for div in soup.find_all("div", class_=True):
        for cls in div.get("class", []):
            if cls.startswith("wistia_async_"):
                h = cls.replace("wistia_async_", "").strip()
                if h and h not in hashes:
                    hashes.append(h)

    # JSON / inline JS — look for hashedId or videoHash patterns
    for script in soup.find_all("script"):
        text = script.string or ""
        for match in re.finditer(r'(?:hashedId|videoHash|wistia)["\s:]*["\']([a-z0-9]{7,14})["\']',
                                 text, re.IGNORECASE):
            h = match.group(1)
            if h not in hashes:
                hashes.append(h)

    # <iframe src="...wistia...">
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "wistia" in src.lower():
            m = re.search(r"/medias?/([a-z0-9]+)", src)
            if m and m.group(1) not in hashes:
                hashes.append(m.group(1))

    return hashes


def extract_other_video_urls(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return (type, url) pairs for Vimeo/YouTube iframes."""
    videos = []
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "vimeo.com" in src:
            videos.append(("vimeo", src))
        elif "youtube.com/embed" in src or "youtu.be" in src:
            videos.append(("youtube", src))
    return videos


# ─── main class ─────────────────────────────────────────────────────────────

class CourseWatcher:
    def __init__(self, email: str, password: str, output_dir: str = "course_output",
                 whisper_model_size: str = "base"):
        self.email = email
        self.password = password
        self.out = Path(output_dir)
        self.out.mkdir(exist_ok=True)
        self.whisper_model_size = whisper_model_size
        self._whisper = None

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ── auth ────────────────────────────────────────────────────────────────

    def login(self):
        print(f"[*] Logging in as {self.email} …")
        r = self.session.get(f"{BASE_URL}/sign_in")
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # Rails CSRF token
        csrf = (
            (soup.find("meta", {"name": "csrf-token"}) or {}).get("content")
            or (soup.find("input", {"name": "authenticity_token"}) or {}).get("value")
        )
        if not csrf:
            raise RuntimeError("Cannot find CSRF token on login page")

        payload = {
            "authenticity_token": csrf,
            "user[email]": self.email,
            "user[password]": self.password,
            "commit": "Sign in",
        }
        r2 = self.session.post(f"{BASE_URL}/sign_in", data=payload, allow_redirects=True)

        if "sign_in" in r2.url or "login" in r2.url.lower():
            # Check for error message
            soup2 = BeautifulSoup(r2.text, "html.parser")
            err = soup2.find(class_=re.compile(r"alert|error|flash", re.I))
            msg = err.get_text(strip=True) if err else "Unknown reason"
            raise RuntimeError(f"Login failed: {msg}")

        print(f"[+] Logged in — redirected to {r2.url}")

    # ── course structure ─────────────────────────────────────────────────────

    def get_lesson_urls(self) -> list[dict]:
        """
        Walk the course index page and collect all /posts/ URLs.
        Falls back to the Kajabi JSON API if the HTML sidebar is empty.
        """
        print(f"\n[*] Fetching course index …")
        r = self.session.get(COURSE_ROOT)
        r.raise_for_status()
        (self.out / "_course_index.html").write_text(r.text, encoding="utf-8")

        soup = BeautifulSoup(r.text, "html.parser")
        lessons = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if "/posts/" in href and f"/products/{COURSE_SLUG}/" in href:
                url = href if href.startswith("http") else BASE_URL + href
                if url not in seen:
                    seen.add(url)
                    lessons.append({"url": url, "title": a.get_text(strip=True)})

        if not lessons:
            print("[!] No lessons found in HTML — trying JSON API …")
            lessons = self._fetch_lessons_via_api()

        print(f"[+] Found {len(lessons)} lessons")
        return lessons

    def _fetch_lessons_via_api(self) -> list[dict]:
        """
        Kajabi exposes a JSON API at /api/v1/products/{slug}/posts
        (or similar). Try common endpoints.
        """
        candidates = [
            f"{BASE_URL}/api/v1/products/{COURSE_SLUG}/posts",
            f"{BASE_URL}/api/v1/products/{COURSE_SLUG}",
            f"{BASE_URL}/products/{COURSE_SLUG}?format=json",
        ]
        for url in candidates:
            try:
                r = self.session.get(url, headers={"Accept": "application/json"}, timeout=10)
                if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                    data = r.json()
                    (self.out / "_api_response.json").write_text(json.dumps(data, indent=2))
                    return self._parse_api_lessons(data)
            except Exception:
                continue

        print("[!] API fallback also returned nothing. The site may be heavily JS-rendered.")
        print(f"    Inspect {self.out / '_course_index.html'} and supply lesson URLs manually.")
        return []

    def _parse_api_lessons(self, data) -> list[dict]:
        lessons = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("posts") or data.get("lessons") or data.get("items") or []
        else:
            return []

        for item in items:
            slug = item.get("slug") or item.get("id")
            cat = item.get("category_id") or item.get("category", {}).get("id", "")
            title = item.get("title") or item.get("name") or str(slug)
            if slug:
                url = f"{COURSE_ROOT}/categories/{cat}/posts/{slug}"
                lessons.append({"url": url, "title": title})
        return lessons

    # ── per-lesson ───────────────────────────────────────────────────────────

    def fetch_lesson(self, url: str) -> dict:
        r = self.session.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        title = ""
        h = soup.find(re.compile(r"^h[123]$"))
        if h:
            title = h.get_text(strip=True)
        if not title:
            title = (soup.title or soup).get_text(strip=True)[:120]

        # Body text (skip nav/header/footer)
        for tag in soup(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        body_text = (soup.find("main") or soup.body or soup).get_text("\n", strip=True)

        wistia_hashes = extract_wistia_hashes(soup)
        other_videos = extract_other_video_urls(soup)

        # Some Kajabi pages embed lesson JSON
        page_json = {}
        for script in soup.find_all("script", type="application/json"):
            try:
                page_json = json.loads(script.string)
                break
            except Exception:
                pass

        return {
            "url": url,
            "title": title,
            "body_text": body_text,
            "wistia_hashes": wistia_hashes,
            "other_videos": other_videos,
            "page_json": page_json,
            "raw_html": r.text,
        }

    # ── video download ───────────────────────────────────────────────────────

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.session.cookies.items())

    def download_wistia(self, hash_id: str, dest: Path) -> Path | None:
        """Try yt-dlp on fast.wistia.net, then wistia.com/medias."""
        urls = [
            f"https://fast.wistia.net/medias/{hash_id}",
            f"https://contentcreator.wistia.com/medias/{hash_id}",
            f"https://home.wistia.com/medias/{hash_id}",
        ]
        for url in urls:
            result = subprocess.run(
                [
                    "yt-dlp", "--no-warnings", "-q",
                    "--add-header", f"Cookie: {self._cookie_header()}",
                    "--add-header", f"Referer: {BASE_URL}/",
                    "-o", str(dest),
                    url,
                ],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and dest.exists():
                return dest
            # yt-dlp may append extension
            for f in dest.parent.glob(dest.stem + ".*"):
                if f.suffix in (".mp4", ".mkv", ".webm", ".m4v"):
                    return f
        return None

    def download_video(self, vtype: str, vref: str, dest: Path) -> Path | None:
        """Generic download via yt-dlp."""
        result = subprocess.run(
            [
                "yt-dlp", "--no-warnings", "-q",
                "--add-header", f"Cookie: {self._cookie_header()}",
                "-o", str(dest),
                vref,
            ],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and dest.exists():
            return dest
        for f in dest.parent.glob(dest.stem + ".*"):
            if f.suffix in (".mp4", ".mkv", ".webm", ".m4v"):
                return f
        return None

    # ── transcription ────────────────────────────────────────────────────────

    def transcribe(self, video_path: Path) -> str:
        if self._whisper is None:
            import whisper
            print(f"  [*] Loading Whisper '{self.whisper_model_size}' model …")
            self._whisper = whisper.load_model(self.whisper_model_size)
        print(f"  [*] Transcribing {video_path.name} …")
        result = self._whisper.transcribe(str(video_path), fp16=False)
        return result["text"].strip()

    # ── notes rendering ──────────────────────────────────────────────────────

    @staticmethod
    def render_notes(lesson: dict, transcript: str) -> str:
        lines = [f"# {lesson['title']}", f"\n**URL:** {lesson['url']}\n", "---\n"]
        if transcript:
            lines += ["## Full Video Transcript\n", transcript, "\n---\n"]
        if lesson["body_text"]:
            lines += ["## Lesson Page Content\n", lesson["body_text"]]
        return "\n".join(lines)

    # ── per-lesson pipeline ──────────────────────────────────────────────────

    def process_lesson(self, url: str, idx: int) -> dict:
        print(f"\n─── Lesson {idx}: {url}")
        lesson = self.fetch_lesson(url)
        title = lesson["title"] or f"lesson_{idx}"
        print(f"    Title: {title}")

        lesson_dir = self.out / f"{idx:03d}_{safe_name(title)}"
        lesson_dir.mkdir(exist_ok=True)
        (lesson_dir / "page.html").write_text(lesson["raw_html"], encoding="utf-8")

        transcript = ""

        # ── Wistia ────────────────────────────────────────────────────────
        for i, h in enumerate(lesson["wistia_hashes"]):
            print(f"  [*] Wistia hash: {h}")
            dest = lesson_dir / f"video_wistia_{i}"
            path = self.download_wistia(h, dest)
            if path:
                print(f"  [+] Downloaded: {path.name}")
                try:
                    transcript = self.transcribe(path)
                    (lesson_dir / f"transcript_wistia_{i}.txt").write_text(transcript, encoding="utf-8")
                    print(f"  [+] Transcript: {len(transcript)} chars")
                except Exception as e:
                    print(f"  [!] Transcription error: {e}")
            else:
                print(f"  [!] Could not download Wistia video {h}")

        # ── Other (Vimeo / YouTube) ───────────────────────────────────────
        for i, (vtype, vref) in enumerate(lesson["other_videos"]):
            print(f"  [*] {vtype} video: {vref[:80]}")
            dest = lesson_dir / f"video_{vtype}_{i}"
            path = self.download_video(vtype, vref, dest)
            if path:
                print(f"  [+] Downloaded: {path.name}")
                try:
                    transcript = transcript or self.transcribe(path)
                    (lesson_dir / f"transcript_{vtype}_{i}.txt").write_text(transcript, encoding="utf-8")
                except Exception as e:
                    print(f"  [!] Transcription error: {e}")
            else:
                print(f"  [!] Could not download {vtype} video")

        notes = self.render_notes(lesson, transcript)
        (lesson_dir / "notes.md").write_text(notes, encoding="utf-8")

        return {"url": url, "title": title, "transcript": transcript, "notes": notes}

    # ── main ─────────────────────────────────────────────────────────────────

    def run(self):
        self.login()
        lessons = self.get_lesson_urls()

        if not lessons:
            print("\n[!] No lessons found. Check _course_index.html for the raw page.")
            sys.exit(1)

        results = []
        for i, lesson in enumerate(lessons, 1):
            try:
                result = self.process_lesson(lesson["url"], i)
                results.append(result)
            except Exception as e:
                print(f"  [!] Error on lesson {i}: {e}")
            time.sleep(1.5)

        # Master notes
        master = self.out / "MASTER_NOTES.md"
        with master.open("w", encoding="utf-8") as f:
            f.write(f"# AI Creator Course — Complete Notes\n\n")
            f.write(f"*{len(results)} lessons processed*\n\n---\n\n")
            for r in results:
                f.write(f"\n\n{r['notes']}\n\n---\n")
        print(f"\n[+] Done! Master notes → {master}")

        return results


# ─── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watch and transcribe a contentcreator.com course")
    parser.add_argument("--email",    default=os.environ.get("COURSE_EMAIL"),    help="Login email")
    parser.add_argument("--password", default=os.environ.get("COURSE_PASSWORD"), help="Login password")
    parser.add_argument("--output",   default="course_output",                   help="Output directory")
    parser.add_argument("--model",    default="base",
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model size (larger = slower but more accurate)")
    args = parser.parse_args()

    if not args.email or not args.password:
        print("Error: supply --email / --password or COURSE_EMAIL / COURSE_PASSWORD env vars")
        sys.exit(1)

    watcher = CourseWatcher(
        email=args.email,
        password=args.password,
        output_dir=args.output,
        whisper_model_size=args.model,
    )
    watcher.run()
