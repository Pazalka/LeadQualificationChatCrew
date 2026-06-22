#!/usr/bin/env python3
"""
Fix the 6 remaining lessons:
  - 019: JS-rendered Wistia (paywall div, hash not in HTML) -> try Kajabi JSON API
  - 051: Wistia video 4GB > Gemini limit -> extract audio only + Whisper
  - 052-055: 0-byte page.html -> re-fetch, look for videos

Usage:
    GEMINI_API_KEY=... COURSE_EMAIL=... COURSE_PASSWORD=... python fix_remaining.py
"""

import os, re, sys, json, time, subprocess
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import whisper

BASE_URL   = "https://www.contentcreator.com"
COURSE_SLUG = "ai-creator-course"
COURSE_ROOT = f"{BASE_URL}/products/{COURSE_SLUG}"
OUTPUT_DIR  = Path("course_output")
YT_DLP_CMD  = [sys.executable, "-m", "yt_dlp"]

# Lesson index -> URL mapping (1-based, matching directory numbers)
# Extracted from _course_index.html
LESSON_URLS = [
    None,  # placeholder so index 1 = first lesson
    f"{BASE_URL}/products/ai-creator-course/categories/2157412656/posts/2186653204",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412656/posts/2186653205",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412656/posts/2186925068",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412657/posts/2186653208",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412657/posts/2186653207",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412657/posts/2196584465",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412657/posts/2186925185",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412657/posts/2197042675",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412657/posts/2186653209",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2186653210",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2190797751",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2197590887",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2186925202",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2186925210",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2186925223",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2186925229",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412658/posts/2190702452",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412659/posts/2190797801",
    f"{BASE_URL}/products/ai-creator-course/categories/2157412659/posts/2195493595",  # 019
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2194080911",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2186925504",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2187033318",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2192666653",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2193539833",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2190276045",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2197590891",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2197590892",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2197590890",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469701/posts/2192689182",
    f"{BASE_URL}/products/ai-creator-course/categories/2159256926/posts/2194234933",
    f"{BASE_URL}/products/ai-creator-course/categories/2159256926/posts/2194080910",
    f"{BASE_URL}/products/ai-creator-course/categories/2159256926/posts/2194175296",
    f"{BASE_URL}/products/ai-creator-course/categories/2159256926/posts/2195581486",
    f"{BASE_URL}/products/ai-creator-course/categories/2159572716/posts/2197590889",
    f"{BASE_URL}/products/ai-creator-course/categories/2159572716/posts/2197590888",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925418",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925426",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925429",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925433",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925439",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925447",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2186925451",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469703/posts/2190229233",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2192332531",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2192332519",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2187646923",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2187498600",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2187505462",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2186925517",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2186925520",
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2187648779",  # 051
    f"{BASE_URL}/products/ai-creator-course/categories/2157469702/posts/2194080909",  # 052
    f"{BASE_URL}/products/ai-creator-course/categories/2159573207/posts/2195495371",  # 053
    f"{BASE_URL}/products/ai-creator-course/categories/2159573207/posts/2195495375",  # 054
    f"{BASE_URL}/products/ai-creator-course/categories/2159573207/posts/2195495409",  # 055
]

TARGETS = [19, 51, 52, 53, 54, 55]


def login(email, password):
    print(f"[*] Logging in ...")
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/124"})
    r = s.get(f"{BASE_URL}/login"); r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    inp  = soup.find("input", {"name": "authenticity_token"})
    csrf = (meta["content"] if meta else None) or (inp["value"] if inp else None)
    r2 = s.post(f"{BASE_URL}/login", data={
        "authenticity_token": csrf,
        "member[email]": email, "member[password]": password,
    }, allow_redirects=True)
    if "/login" in r2.url.lower(): raise RuntimeError("Login failed")
    print(f"[+] Logged in")
    return s


def extract_wistia_hashes(html):
    soup = BeautifulSoup(html, "html.parser")
    hashes = []
    for div in soup.find_all("div", class_=True):
        for cls in div.get("class", []):
            if cls.startswith("wistia_async_"):
                h = cls.replace("wistia_async_", "").strip()
                if h and h not in hashes: hashes.append(h)
    for script in soup.find_all("script"):
        text = script.string or ""
        for m in re.finditer(r'(?:hashedId|videoHash|wistia)["\s:]*["\']([a-z0-9]{7,14})["\']', text, re.I):
            h = m.group(1)
            if h not in hashes: hashes.append(h)
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "wistia" in src.lower():
            m = re.search(r"/medias?/([a-z0-9]+)", src)
            if m and m.group(1) not in hashes: hashes.append(m.group(1))
    # Also search raw HTML for any alphanumeric Wistia-style hashes near "wistia"
    for m in re.finditer(r'wistia[^"\']{0,50}["\']([a-z0-9]{7,14})["\']', html, re.I):
        h = m.group(1)
        if h not in hashes: hashes.append(h)
    return hashes


def try_kajabi_json_api(session, url):
    """Try Kajabi's JSON endpoints to get video metadata."""
    post_id = url.rstrip("/").split("/")[-1]
    cat_id  = url.split("/categories/")[1].split("/")[0]
    candidates = [
        f"{BASE_URL}/api/v1/products/{COURSE_SLUG}/categories/{cat_id}/posts/{post_id}",
        f"{BASE_URL}/api/v1/products/{COURSE_SLUG}/posts/{post_id}",
        f"{url}?format=json",
    ]
    for api_url in candidates:
        try:
            r = session.get(api_url, headers={"Accept": "application/json"}, timeout=10)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                data = r.json()
                # Look for wistia hash in JSON
                text = json.dumps(data)
                for m in re.finditer(r'["\']([a-z0-9]{7,14})["\']', text):
                    h = m.group(1)
                    # Verify it's a real Wistia hash by checking the oEmbed API
                    check = requests.get(
                        f"https://fast.wistia.com/oembed.json?url=https://home.wistia.com/medias/{h}",
                        timeout=5
                    )
                    if check.status_code == 200 and "title" in check.text:
                        return h
        except Exception:
            continue
    return None


def get_stream_url(hash_id, cookie_header):
    for url in [
        f"https://fast.wistia.net/medias/{hash_id}",
        f"https://home.wistia.com/medias/{hash_id}",
    ]:
        r = subprocess.run(
            YT_DLP_CMD + ["--get-url", "--no-warnings",
                          "--add-header", f"Cookie: {cookie_header}",
                          "--add-header", f"Referer: {BASE_URL}/", url],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                if line.startswith("http"): return line.strip()
    return None


def download_audio_only(hash_id, dest_mp3, cookie_header):
    """Download audio stream only (much smaller than full video)."""
    for url in [
        f"https://fast.wistia.net/medias/{hash_id}",
        f"https://home.wistia.com/medias/{hash_id}",
    ]:
        r = subprocess.run(
            YT_DLP_CMD + [
                "--no-warnings", "-q",
                "-x", "--audio-format", "mp3", "--audio-quality", "5",
                "--add-header", f"Cookie: {cookie_header}",
                "--add-header", f"Referer: {BASE_URL}/",
                "-o", str(dest_mp3),
                url,
            ],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            for f in dest_mp3.parent.glob(dest_mp3.stem + ".*"):
                if f.suffix in (".mp3", ".m4a", ".ogg", ".wav", ".aac"):
                    return f
        if dest_mp3.exists(): return dest_mp3
    return None


def whisper_transcribe(audio_path, model_size="base"):
    print(f"  [*] Loading Whisper '{model_size}' ...")
    model = whisper.load_model(model_size)
    print(f"  [*] Transcribing {audio_path.name} ...")
    result = model.transcribe(str(audio_path), fp16=False)
    return result["text"].strip()


def update_notes(lesson_dir, transcript, source="Whisper"):
    notes_path = lesson_dir / "notes.md"
    existing = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    if "## Full Video Transcript" not in existing:
        with notes_path.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Full Video Transcript (via {source})\n\n{transcript}\n")


def build_master_notes():
    notes_files = sorted(OUTPUT_DIR.glob("*/notes.md"))
    master = OUTPUT_DIR / "MASTER_NOTES.md"
    with master.open("w", encoding="utf-8") as f:
        f.write(f"# AI Creator Course -- Complete Notes\n\n*{len(notes_files)} lessons*\n\n---\n\n")
        for nf in notes_files:
            f.write(f"\n\n{nf.read_text(encoding='utf-8')}\n\n---\n")
    print(f"[+] MASTER_NOTES.md written ({len(notes_files)} lessons)")


def main():
    email    = os.environ.get("COURSE_EMAIL")
    password = os.environ.get("COURSE_PASSWORD")
    if not email or not password:
        print("Error: set COURSE_EMAIL and COURSE_PASSWORD")
        sys.exit(1)

    session = login(email, password)
    cookie_header = "; ".join(f"{k}={v}" for k, v in session.cookies.items())

    for idx in TARGETS:
        url        = LESSON_URLS[idx]
        lesson_dir = next((d for d in OUTPUT_DIR.iterdir()
                           if d.is_dir() and d.name.startswith(f"{idx:03d}_")), None)
        if not lesson_dir:
            print(f"[!] No directory found for lesson {idx}")
            continue

        print(f"\n=== Lesson {idx}: {lesson_dir.name}")

        # Re-fetch page if empty
        page_path = lesson_dir / "page.html"
        if page_path.stat().st_size == 0:
            print(f"  [*] Re-fetching page ...")
            r = session.get(url)
            if r.status_code == 200:
                page_path.write_text(r.text, encoding="utf-8")
                print(f"  [+] Page fetched ({len(r.text)} chars)")
            else:
                print(f"  [!] HTTP {r.status_code}, skipping")
                continue

        html = page_path.read_text(encoding="utf-8", errors="replace")

        # Already has transcript?
        if list(lesson_dir.glob("transcript_*.txt")):
            print(f"  [+] Already has transcript, skipping")
            continue

        # Find Wistia hash
        hashes = extract_wistia_hashes(html)

        if not hashes:
            print(f"  [*] No hash in HTML, trying Kajabi JSON API ...")
            h = try_kajabi_json_api(session, url)
            if h:
                print(f"  [+] Found hash via API: {h}")
                hashes = [h]
            else:
                print(f"  [!] No video found for lesson {idx} - may be text-only")
                continue

        for i, h in enumerate(hashes):
            print(f"  [*] Wistia hash: {h}")

            # Lesson 051: audio-only to stay within disk/Gemini limits
            if idx == 51:
                print(f"  [*] Large video - extracting audio only ...")
                dest = lesson_dir / f"audio_wistia_{i}"
                audio_path = download_audio_only(h, dest, cookie_header)
                if audio_path:
                    print(f"  [+] Audio: {audio_path.name} ({audio_path.stat().st_size // (1024*1024)} MB)")
                    try:
                        transcript = whisper_transcribe(audio_path)
                        audio_path.unlink()  # delete audio after transcribing
                        (lesson_dir / f"transcript_wistia_{i}.txt").write_text(transcript, encoding="utf-8")
                        update_notes(lesson_dir, transcript, source="Whisper (audio-only)")
                        print(f"  [+] Transcript: {len(transcript)} chars")
                    except Exception as e:
                        print(f"  [!] Transcription error: {e}")
                else:
                    print(f"  [!] Audio download failed")
                continue

            # Other lessons: get stream URL for Gemini
            stream_url = get_stream_url(h, cookie_header)
            if not stream_url:
                print(f"  [!] Could not get stream URL")
                continue

            # Download + upload to Gemini
            try:
                from google import genai
                from google.genai import types
                api_key = os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    print("  [!] No GEMINI_API_KEY - falling back to Whisper")
                    raise ValueError("no key")
                client = genai.Client(api_key=api_key)

                print(f"  [*] Downloading for Gemini ...")
                r = requests.get(stream_url, stream=True, timeout=30)
                tmp = lesson_dir / "_tmp_video.mp4"
                written = 0
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=8*1024*1024):
                        f.write(chunk); written += len(chunk)
                        print(f"    {written//(1024*1024)} MB ...", end="\r")
                print()

                if written > 2 * 1024**3:
                    tmp.unlink()
                    raise ValueError(f"Video {written//(1024*1024)} MB > 2GB Gemini limit")

                print(f"  [*] Uploading to Gemini ...")
                video_file = client.files.upload(file=str(tmp), config={"mime_type": "video/mp4"})
                tmp.unlink()

                while video_file.state.name == "PROCESSING":
                    time.sleep(5)
                    video_file = client.files.get(name=video_file.name)

                title = lesson_dir.name[4:].replace("_", " ")
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[
                        types.Part.from_uri(file_uri=video_file.uri, mime_type="video/mp4"),
                        f"Lesson: '{title}'. Provide a detailed transcript then structured key takeaways.",
                    ],
                )
                client.files.delete(name=video_file.name)
                transcript = response.text
                (lesson_dir / f"transcript_wistia_{i}.txt").write_text(transcript, encoding="utf-8")
                update_notes(lesson_dir, transcript, source="Gemini")
                print(f"  [+] Transcript: {len(transcript)} chars")

            except Exception as e:
                print(f"  [!] Gemini failed ({e}), falling back to Whisper audio ...")
                dest = lesson_dir / f"audio_wistia_{i}"
                audio_path = download_audio_only(h, dest, cookie_header)
                if audio_path:
                    try:
                        transcript = whisper_transcribe(audio_path)
                        audio_path.unlink()
                        (lesson_dir / f"transcript_wistia_{i}.txt").write_text(transcript, encoding="utf-8")
                        update_notes(lesson_dir, transcript, source="Whisper fallback")
                        print(f"  [+] Transcript: {len(transcript)} chars")
                    except Exception as e2:
                        print(f"  [!] Whisper also failed: {e2}")

        time.sleep(1)

    build_master_notes()
    print("\n[+] All done!")


if __name__ == "__main__":
    main()
