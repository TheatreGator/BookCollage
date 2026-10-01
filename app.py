import base64
import hashlib
import io
import json
import math
import random
import re
from collections import Counter
import requests
import streamlit as st
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Book Collage, AI Stats & Bookshelf Maker",
    page_icon="📚",
    layout="wide",
)

# --- SESSION STATE INITIALIZATION ---
if "books" not in st.session_state:
    st.session_state.books = []

if "next_id" not in st.session_state:
    st.session_state.next_id = 1

if "cover_search_results" not in st.session_state:
    st.session_state.cover_search_results = {}

if "processed_uploads" not in st.session_state:
    st.session_state.processed_uploads = {}

if "ai_shelf_cache" not in st.session_state:
    st.session_state.ai_shelf_cache = None

if "ai_stats_cache" not in st.session_state:
    st.session_state.ai_stats_cache = None

if "last_ai_shelf_error" not in st.session_state:
    st.session_state.last_ai_shelf_error = None

NONFICTION_KEYWORDS = {
    "nonfiction", "non-fiction", "biography", "biographies", "memoir", "memoirs",
    "history", "historical", "science", "psychology", "business", "economics",
    "self-help", "self-improvement", "philosophy", "politics", "health", "mind",
    "body", "cooking", "travel", "true crime", "essays", "reference", "education",
    "computers", "technology", "religion", "spirituality", "art", "music", "nature",
    "government", "society", "social science",
}

FICTION_HINTS = {
    "fiction", "novel", "fantasy", "sci-fi", "science fiction", "romance",
    "thriller", "mystery", "mysteries", "horror", "historical fiction",
    "literary", "classics", "young adult", "ya", "dystopian", "adventure",
}

SHELF_THEMES = {
    "Warm Oak": {
        "frame": (122, 76, 36),
        "plank": (148, 94, 46),
        "plank_edge": (182, 122, 68),
        "back": (54, 33, 16),
        "grain_dark": (84, 48, 20),
    },
    "Dark Walnut": {
        "frame": (52, 32, 20),
        "plank": (68, 42, 26),
        "plank_edge": (96, 62, 40),
        "back": (26, 15, 9),
        "grain_dark": (34, 19, 10),
    },
    "Minimalist White": {
        "frame": (226, 223, 218),
        "plank": (240, 238, 234),
        "plank_edge": (252, 251, 249),
        "back": (175, 171, 164),
        "grain_dark": (205, 201, 194),
    },
    "Forest Sage": {
        "frame": (50, 68, 55),
        "plank": (64, 86, 71),
        "plank_edge": (88, 114, 96),
        "back": (28, 40, 32),
        "grain_dark": (38, 52, 42),
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def get_secret_or_default(key_name: str) -> str:
    try:
        return st.secrets.get(key_name, "")
    except Exception:
        return ""


# --- SIDEBAR: FREE AI & API SETUP ---
with st.sidebar:
    st.header("🔑 Free AI Setup")
    st.caption("Add a free **Gemini** or **Groq** key to enable AI image generation and literary analysis.")

    ai_provider = st.selectbox(
        "AI Provider",
        ["Google Gemini (Free Tier)", "Groq Cloud (Free Tier)", "None (Offline Rules)"],
    )

    gemini_key = ""
    groq_key = ""

    if ai_provider == "Google Gemini (Free Tier)":
        gemini_key = st.text_input(
            "Gemini API Key",
            value=get_secret_or_default("GEMINI_API_KEY"),
            type="password",
            placeholder="AIzaSy...",
            help="Get a free key from https://aistudio.google.com/apikey",
        )
        st.markdown("👉 [Get free Gemini key](https://aistudio.google.com/apikey)")
    elif ai_provider == "Groq Cloud (Free Tier)":
        groq_key = st.text_input(
            "Groq API Key",
            value=get_secret_or_default("GROQ_API_KEY"),
            type="password",
            placeholder="gsk_...",
            help="Get a free key from https://console.groq.com/keys",
        )
        st.markdown("👉 [Get free Groq key](https://console.groq.com/keys)")

    st.divider()
    google_books_key = st.text_input(
        "Google Books API Key (Optional)",
        value=get_secret_or_default("GOOGLE_BOOKS_API_KEY"),
        type="password",
        help="Optional: prevents Google Books rate limits.",
    )


# --- FONT & COLOR HELPERS ---
def get_font(size: int, bold: bool = False):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=max(9, int(size)))
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=max(9, int(size)))
    except TypeError:
        return ImageFont.load_default()


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = hex_to_rgb(hex_color)
    return (r, g, b, alpha)


def blend_rgb(bg_hex: str, fg_hex: str, weight: float) -> tuple[int, int, int]:
    r1, g1, b1 = hex_to_rgb(bg_hex)
    r2, g2, b2 = hex_to_rgb(fg_hex)
    w = max(0.0, min(1.0, weight))
    return (
        int(r1 * (1.0 - w) + r2 * w),
        int(g1 * (1.0 - w) + g2 * w),
        int(b1 * (1.0 - w) + b2 * w),
    )


def extract_dominant_color(pil_img: Image.Image) -> str:
    try:
        small = pil_img.convert("RGB").resize((48, 48), Image.Resampling.BILINEAR)
        quantized = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT).convert("RGB")
        try:
            raw_pixels = list(quantized.get_flattened_data())
            pixel_tuples = [(raw_pixels[i], raw_pixels[i + 1], raw_pixels[i + 2]) for i in range(0, len(raw_pixels), 3)]
        except AttributeError:
            pixel_tuples = list(quantized.getdata())

        counts = Counter(pixel_tuples)
        best_rgb = (68, 92, 78)
        best_score = -1.0
        for (r, g, b), count in counts.items():
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if 22 < lum < 230:
                saturation = (max(r, g, b) - min(r, g, b)) / 255.0
                score = count * (1.0 + saturation * 1.4)
                if score > best_score:
                    best_score = score
                    best_rgb = (r, g, b)

        if best_score < 0 and counts:
            best_rgb = counts.most_common(1)[0][0]
        return "#{:02x}{:02x}{:02x}".format(*best_rgb)
    except Exception:
        return "#4A6151"


# --- AI INSIGHT ENGINE (GEMINI & GROQ) ---
def generate_ai_stats_analysis(books: list, gemini_api_key: str = "", groq_api_key: str = "") -> dict | None:
    if not books or (not gemini_api_key and not groq_api_key):
        return None

    book_list_str = "\n".join(
        [f"- '{b['title']}' by {b.get('author','')} ({b.get('genre','')}, {b.get('category','')}, {b.get('pages', 300)} pages)" for b in books]
    )

    prompt = (
        "You are an acclaimed cultural critic and literary theorist performing a psychological/thematic deep-dive on a reader's book list.\n"
        f"Reading List:\n{book_list_str}\n\n"
        "Deliver a sharp analysis formatted strictly as a single JSON object with these keys:\n"
        "{\n"
        '  "archetype": "A captivating 2-4 word reader title (e.g. \'The Pragmatic World-Builder\', \'Subversive Realist\', \'Existential Architect\')",\n'
        '  "thesis": "A concise 2-sentence synthesis identifying the underlying philosophical conflict or curiosity driving their book selections.",\n'
        '  "fixation": "A single phrase naming their subconscious obsession across these books (e.g., \'Systemic Collapse vs. Personal Agency\')",\n'
        '  "collision": "Name TWO contrasting books from their list and write 1 sharp sentence on what happens when their core ideas collide.",\n'
        '  "tone_words": ["WORD1", "WORD2", "WORD3", "WORD4"]\n'
        "}"
    )

    if gemini_api_key:
        for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
                }
                resp = requests.post(
                    url,
                    headers={"x-goog-api-key": gemini_api_key.strip(), "Content-Type": "application/json"},
                    json=payload,
                    timeout=14,
                )
                if resp.status_code == 200:
                    text_out = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(text_out)
            except Exception:
                continue

    if groq_api_key:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You output only valid, parseable JSON."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.4,
            }
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {groq_api_key.strip()}", "Content-Type": "application/json"},
                json=payload,
                timeout=12,
            )
            if resp.status_code == 200:
                text_out = resp.json()["choices"][0]["message"]["content"]
                return json.loads(text_out)
        except Exception:
            pass

    return None


# --- AI PHOTOREALISTIC BOOKSHELF GENERATION ---
def generate_ai_photorealistic_bookshelf(
    books: list,
    wood_style: str,
    gemini_api_key: str,
    aspect_ratio: str = "4:5",
) -> tuple[Image.Image | None, str | None]:
    if not books:
        return None, "No books added yet."

    book_titles = ", ".join([f"'{b['title']}' by {b.get('author','')}" for b in books[:16]])
    clean_prompt = (
        f"A masterwork editorial studio photograph of a luxury {wood_style} wooden bookcase shelf. "
        f"Arranged neatly on the shelf are physical books with sharp, legible spines showing: {book_titles}. "
        "Intricate real textures: matte dust jackets, embossed gold foil stamping, ribbed cloth bindings, "
        "and cream-colored paper block tops. Volumetric studio rim-lighting, organic wood grain, shallow depth of field, 8k resolution, cinematic lighting."
    )

    ar_map = {
        "Instagram Story / TikTok (1080 x 1920)": "9:16",
        "Instagram Portrait Post (1080 x 1350)": "4:5",
        "Instagram Square Post (1080 x 1080)": "1:1",
        "X / Twitter Landscape (1600 x 900)": "16:9",
    }
    target_ar = ar_map.get(aspect_ratio, "4:5")

    # 1. Try Google Imagen 3 via Gemini API Key
    if gemini_api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={gemini_api_key.strip()}"
            payload = {
                "instances": [{"prompt": clean_prompt}],
                "parameters": {
                    "sampleCount": 1,
                    "aspectRatio": target_ar,
                    "outputMimeType": "image/jpeg",
                },
            }
            resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
            if resp.status_code == 200:
                predictions = resp.json().get("predictions", [])
                if predictions and "bytesBase64Encoded" in predictions[0]:
                    b64 = predictions[0]["bytesBase64Encoded"]
                    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB"), None
            else:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
                st.session_state.last_ai_shelf_error = f"Imagen API Error ({resp.status_code}): {err_msg}"
        except Exception as e:
            st.session_state.last_ai_shelf_error = f"Network Exception: {str(e)}"

    # 2. Reliable Fallback (Pollinations Flux AI Image Engine - No Key Required)
    try:
        dim_map = {
            "9:16": (768, 1344),
            "4:5": (896, 1152),
            "1:1": (1024, 1024),
            "16:9": (1280, 720),
        }
        w, h = dim_map.get(target_ar, (896, 1152))
        enc_prompt = requests.utils.quote(clean_prompt[:450])
        poll_url = f"https://image.pollinations.ai/prompt/{enc_prompt}?width={w}&height={h}&model=flux&nologo=true&seed=42"
        resp = requests.get(poll_url, timeout=24)
        if resp.status_code == 200 and len(resp.content) > 10000:
            return Image.open(io.BytesIO(resp.content)).convert("RGB"), None
    except Exception as e:
        pass

    return None, st.session_state.last_ai_shelf_error or "Unable to generate image with available endpoints."


# --- METADATA & SEARCH ENGINE ---
def parse_title_author(raw_query: str) -> tuple[str, str]:
    q = raw_query.strip()
    by_match = re.split(r"\s+by\s+", q, maxsplit=1, flags=re.IGNORECASE)
    if len(by_match) == 2:
        return by_match[0].strip(), by_match[1].strip()
    dash_match = re.split(r"\s+[-–—]\s+", q, maxsplit=1)
    if len(dash_match) == 2:
        return dash_match[0].strip(), dash_match[1].strip()
    return q, ""


def significant_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stopwords = {"the", "a", "an", "by"}
    filtered = [w for w in words if w not in stopwords]
    return filtered if filtered else words


def verify_exact_match(req_title: str, req_author: str, cand_title: str, cand_author: str) -> float:
    if not cand_title:
        return 0.0
    req_t_words = significant_words(req_title)
    cand_t_words = set(significant_words(cand_title))
    cand_all_words = set(significant_words(f"{cand_title} {cand_author}"))

    if not req_t_words:
        return 0.0

    matched_title_words = sum(1 for w in req_t_words if w in cand_t_words)
    title_hit_ratio = matched_title_words / len(req_t_words)

    if not req_author:
        all_hits = sum(1 for w in req_t_words if w in cand_all_words)
        combined_ratio = all_hits / len(req_t_words)
        cand_main = significant_words(re.split(r"[:(\-–]", cand_title)[0])
        main_hits = sum(1 for w in cand_main if w in set(req_t_words))
        main_ratio = main_hits / max(1, len(cand_main))
        if combined_ratio >= 0.85 and main_ratio >= 0.75:
            return 0.85 + combined_ratio * 0.15
        if title_hit_ratio < 0.75:
            return 0.0
    else:
        min_required = 1.0 if len(req_t_words) <= 3 else 0.78
        if title_hit_ratio < min_required:
            return 0.0

    author_score = 0.5
    if req_author:
        req_a_words = significant_words(req_author)
        cand_a_words = set(significant_words(cand_author))
        if req_a_words:
            a_hits = sum(1 for w in req_a_words if w in cand_a_words)
            if a_hits == 0 and cand_a_words:
                return 0.0
            author_score = a_hits / len(req_a_words)

    cand_main_str = " ".join(significant_words(re.split(r"[:(\-–]", cand_title)[0]))
    req_main_str = " ".join(req_t_words)
    exact_bonus = 0.2 if cand_main_str == req_main_str else 0.0

    return title_hit_ratio * 0.65 + author_score * 0.35 + exact_bonus


def download_valid_image(url: str) -> bytes | None:
    if not url:
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200 and len(resp.content) > 1500:
            img = Image.open(io.BytesIO(resp.content))
            if img.width > 50 and img.height > 50:
                return resp.content
    except Exception:
        pass
    return None


def classify_fiction_nonfiction(genre_str: str, subjects: list[str]) -> tuple[str, str]:
    combined = " ".join([genre_str] + subjects[:10]).lower()
    is_nonfic = any(kw in combined for kw in NONFICTION_KEYWORDS)
    is_fic = any(kw in combined for kw in FICTION_HINTS)

    if is_nonfic and not ("historical fiction" in combined or "science fiction" in combined):
        category = "Non-Fiction"
    elif is_fic:
        category = "Fiction"
    else:
        category = "Fiction"

    clean_genre = genre_str.strip() if genre_str else ""
    if not clean_genre or clean_genre.lower() in {"books", "general", "ebook", "audiobooks"}:
        for s in subjects:
            s_low = s.lower()
            if len(s) < 24 and s_low not in {"fiction", "nonfiction", "accessible book"}:
                clean_genre = s.title()
                break
    if not clean_genre:
        clean_genre = "General Fiction" if category == "Fiction" else "General Non-Fiction"

    genre_map = {
        "Fiction & Literature": "Literary Fiction",
        "Mysteries & Thrillers": "Mystery & Thriller",
        "Sci-Fi & Fantasy": "Sci-Fi & Fantasy",
        "Biographies & Memoirs": "Biography & Memoir",
        "Health, Mind & Body": "Health & Psychology",
        "Business & Personal Finance": "Business",
        "Politics & Current Events": "Politics & Society",
    }
    return genre_map.get(clean_genre, clean_genre), category


def fetch_book_data(raw_query: str, gb_api_key: str = "") -> dict:
    req_title, req_author = parse_title_author(raw_query)
    exact_search = f"{req_title} {req_author}".strip()
    candidates = []
    img_bytes = None

    # Google Books
    for gb_query in (exact_search, raw_query.strip()):
        try:
            gb_params = {"q": gb_query, "maxResults": 6}
            if gb_api_key:
                gb_params["key"] = gb_api_key.strip()
            resp = requests.get("https://www.googleapis.com/books/v1/volumes", params=gb_params, headers=HEADERS, timeout=7)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    vol = item.get("volumeInfo", {})
                    c_title = vol.get("title", "")
                    c_sub = vol.get("subtitle", "")
                    full_c_title = f"{c_title}: {c_sub}" if c_sub else c_title
                    c_authors = vol.get("authors", [""])
                    c_author = ", ".join(c_authors)

                    score = verify_exact_match(req_title, req_author, full_c_title, c_author)
                    if score > 0:
                        links = vol.get("imageLinks", {})
                        thumb = links.get("thumbnail") or links.get("smallThumbnail") or ""
                        high_res = thumb.replace("http://", "https://").replace("&edge=curl", "").replace("zoom=1", "zoom=2")
                        yr = None
                        if vol.get("publishedDate"):
                            m = re.match(r"(\d{4})", str(vol["publishedDate"]))
                            if m:
                                yr = int(m.group(1))
                        candidates.append({
                            "score": score + 0.05,
                            "title": c_title,
                            "author": c_authors[0] if c_authors else "",
                            "cover_url": high_res,
                            "fallback_url": thumb.replace("http://", "https://").replace("&edge=curl", ""),
                            "primary_genre": "",
                            "subjects": vol.get("categories", []),
                            "year": yr,
                            "pages": int(vol["pageCount"]) if vol.get("pageCount") else None,
                        })
                if candidates:
                    break
        except Exception:
            pass

    # Open Library
    try:
        params = {"q": exact_search, "fields": "title,author_name,cover_i,first_publish_year,number_of_pages_median,subject", "limit": 6}
        resp = requests.get("https://openlibrary.org/search.json", params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            for doc in resp.json().get("docs", []):
                c_title = doc.get("title", "")
                c_authors = doc.get("author_name", [""])
                score = verify_exact_match(req_title, req_author, c_title, ", ".join(c_authors))
                if score > 0:
                    cov_id = doc.get("cover_i")
                    candidates.append({
                        "score": score,
                        "title": c_title,
                        "author": c_authors[0] if c_authors else "",
                        "cover_url": f"https://covers.openlibrary.org/b/id/{cov_id}-L.jpg" if cov_id else "",
                        "fallback_url": "",
                        "primary_genre": "",
                        "subjects": doc.get("subject", [])[:10],
                        "year": int(doc["first_publish_year"]) if doc.get("first_publish_year") else None,
                        "pages": int(doc["number_of_pages_median"]) if doc.get("number_of_pages_median") else None,
                    })
    except Exception:
        pass

    candidates.sort(key=lambda x: x["score"], reverse=True)
    display_title = req_title.title() if req_title.islower() else req_title
    display_author = req_author.title() if req_author.islower() else req_author
    subjects, year, pages, primary_genre = [], None, None, ""

    if candidates:
        if not display_author and candidates[0]["author"]:
            display_author = candidates[0]["author"]
        for cand in candidates:
            if img_bytes is None and cand["cover_url"]:
                img_bytes = download_valid_image(cand["cover_url"]) or download_valid_image(cand.get("fallback_url"))
            if not pages and cand["pages"]:
                pages = cand["pages"]
            if not year and cand["year"]:
                year = cand["year"]
            if cand["subjects"]:
                subjects.extend(cand["subjects"])

    clean_genre, category = classify_fiction_nonfiction(primary_genre, subjects)
    return {
        "title": display_title,
        "author": display_author,
        "img_bytes": img_bytes,
        "genre": clean_genre,
        "category": category,
        "year": year if year else 2024,
        "pages": pages if pages else 320,
    }


def search_cover_candidates_with_stats(query: str, gb_api_key: str = "", max_results: int = 6) -> list[dict]:
    q = query.strip()
    results = []
    seen_urls = set()

    # Google Books
    try:
        gb_params = {"q": q, "maxResults": 6}
        if gb_api_key:
            gb_params["key"] = gb_api_key.strip()
        resp = requests.get("https://www.googleapis.com/books/v1/volumes", params=gb_params, headers=HEADERS, timeout=6)
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                vol = item.get("volumeInfo", {})
                links = vol.get("imageLinks", {})
                thumb = links.get("thumbnail") or links.get("smallThumbnail")
                if thumb:
                    url = thumb.replace("http://", "https://").replace("&edge=curl", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        b_img = download_valid_image(url)
                        if b_img:
                            c_genre, c_cat = classify_fiction_nonfiction("", vol.get("categories", []))
                            yr = 2024
                            if vol.get("publishedDate"):
                                m = re.match(r"(\d{4})", str(vol["publishedDate"]))
                                if m:
                                    yr = int(m.group(1))
                            authors = vol.get("authors", [""])
                            results.append({
                                "title": vol.get("title", q),
                                "author": authors[0] if authors else "",
                                "source": "Google Books",
                                "img_bytes": b_img,
                                "pages": int(vol.get("pageCount", 320)),
                                "year": yr,
                                "genre": c_genre,
                                "category": c_cat,
                            })
                            if len(results) >= max_results:
                                return results
    except Exception:
        pass

    # Open Library
    try:
        resp = requests.get("https://openlibrary.org/search.json", params={"q": q, "fields": "title,author_name,cover_i,number_of_pages_median,first_publish_year,subject", "limit": 5}, headers=HEADERS, timeout=7)
        if resp.status_code == 200:
            for doc in resp.json().get("docs", []):
                cov_id = doc.get("cover_i")
                if cov_id:
                    url = f"https://covers.openlibrary.org/b/id/{cov_id}-L.jpg"
                    if url not in seen_urls:
                        seen_urls.add(url)
                        b_img = download_valid_image(url)
                        if b_img:
                            authors = doc.get("author_name", [""])
                            c_genre, c_cat = classify_fiction_nonfiction("", doc.get("subject", []))
                            results.append({
                                "title": doc.get("title", q),
                                "author": authors[0] if authors else "",
                                "source": "Open Library",
                                "img_bytes": b_img,
                                "pages": int(doc.get("number_of_pages_median", 320)),
                                "year": int(doc.get("first_publish_year", 2024)),
                                "genre": c_genre,
                                "category": c_cat,
                            })
                            if len(results) >= max_results:
                                return results
    except Exception:
        pass

    return results


def create_placeholder_cover(title: str, author: str = "") -> Image.Image:
    width, height = 400, 600
    digest = hashlib.md5(title.encode("utf-8")).hexdigest()
    palette = [(58, 79, 65), (122, 62, 52), (48, 72, 98), (104, 78, 54), (82, 58, 92), (44, 82, 84)]
    bg_rgb = palette[int(digest[:2], 16) % len(palette)]

    img = Image.new("RGB", (width, height), color=bg_rgb)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], outline=(230, 220, 200), width=3)

    font_title = get_font(28, bold=True)
    font_author = get_font(20, bold=False)

    words = title.split()
    lines, current_line = [], ""
    for word in words:
        if len(current_line + " " + word) <= 18:
            current_line = (current_line + " " + word).strip()
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    y_text = 180
    for line in lines[:6]:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        w = bbox[2] - bbox[0]
        draw.text(((width - w) / 2, y_text), line, fill=(255, 250, 240), font=font_title)
        y_text += 40

    if author:
        bbox = draw.textbbox((0, 0), author, font=font_author)
        w = bbox[2] - bbox[0]
        draw.text(((width - w) / 2, height - 100), author, fill=(210, 200, 180), font=font_author)

    return img


def add_rounded_corners(im: Image.Image, radius: int) -> Image.Image:
    if radius <= 0:
        return im.convert("RGBA")
    im = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, im.size[0], im.size[1]), radius=radius, fill=255)
    output = ImageOps.fit(im, mask.size, centering=(0.5, 0.5))
    output.putalpha(mask)
    return output


# --- SLIDE 1: COVER COLLAGE GENERATOR ---
def generate_collage(
    books: list,
    canvas_size: tuple[int, int],
    cols: int,
    gap: int,
    margin: int,
    bg_color: str,
    corner_radius: int,
    add_shadow: bool,
    header_text: str,
    footer_text: str,
    text_color: str,
) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    canvas = Image.new("RGBA", (canvas_w, canvas_h), hex_to_rgba(bg_color, 255))
    draw = ImageDraw.Draw(canvas)

    n_books = len(books)
    if n_books == 0:
        return canvas.convert("RGB")

    rows = math.ceil(n_books / cols)
    top_offset = margin + (110 if header_text.strip() else 0)
    bottom_offset = margin + (70 if footer_text.strip() else 0)

    avail_w = max(100, canvas_w - (2 * margin) - ((cols - 1) * gap))
    avail_h = max(100, canvas_h - top_offset - bottom_offset - ((rows - 1) * gap))

    book_aspect = 1.5
    cell_w = avail_w / cols
    cell_h = avail_h / rows

    if cell_w * book_aspect <= cell_h:
        cover_w = int(cell_w)
        cover_h = int(cell_w * book_aspect)
    else:
        cover_h = int(cell_h)
        cover_w = int(cell_h / book_aspect)

    total_grid_h = rows * cover_h + (rows - 1) * gap
    start_y = top_offset + (avail_h - total_grid_h) // 2
    txt_rgb = hex_to_rgb(text_color)

    if header_text.strip():
        header_font = get_font(52, bold=True)
        bbox = draw.textbbox((0, 0), header_text, font=header_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) / 2, margin + 10), header_text, fill=txt_rgb, font=header_font)

    if footer_text.strip():
        footer_font = get_font(28, bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) / 2, canvas_h - margin - 40), footer_text, fill=txt_rgb, font=footer_font)

    for idx, book in enumerate(books):
        r = idx // cols
        c = idx % cols

        items_in_this_row = cols if (r < rows - 1 or n_books % cols == 0) else (n_books % cols)
        row_width = items_in_this_row * cover_w + (items_in_this_row - 1) * gap
        start_x = (canvas_w - row_width) // 2

        x = start_x + c * (cover_w + gap)
        y = start_y + r * (cover_h + gap)

        cover_img = ImageOps.fit(book["image"].convert("RGBA"), (cover_w, cover_h), Image.Resampling.LANCZOS)
        cover_img = add_rounded_corners(cover_img, corner_radius)

        if add_shadow:
            shadow_offset = max(4, int(cover_w * 0.03))
            shadow_blur = max(6, int(cover_w * 0.04))
            shadow_pad = shadow_blur * 2

            shadow = Image.new("RGBA", (cover_w + shadow_pad * 2, cover_h + shadow_pad * 2), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rounded_rectangle(
                (shadow_pad, shadow_pad, shadow_pad + cover_w, shadow_pad + cover_h),
                radius=corner_radius,
                fill=(0, 0, 0, 110),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
            canvas.alpha_composite(shadow, (x - shadow_pad + shadow_offset, y - shadow_pad + shadow_offset))

        canvas.alpha_composite(cover_img, (x, y))

    return canvas.convert("RGB")


# --- SLIDE 2: EDITORIAL "READING DNA" STATS GRAPHIC ---
def generate_stats_image(
    books: list,
    canvas_size: tuple[int, int],
    margin: int,
    bg_color: str,
    text_color: str,
    accent_color: str,
    header_text: str,
    footer_text: str,
    ai_analysis: dict | None = None,
) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    bg_rgb = hex_to_rgb(bg_color)
    txt_rgb = hex_to_rgb(text_color)
    accent_rgb = hex_to_rgb(accent_color)

    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_rgb)
    draw = ImageDraw.Draw(canvas)

    if not books:
        return canvas

    scale = min(canvas_w / 1080.0, canvas_h / 1080.0)
    pad = max(42, int(margin * 0.85))
    content_w = canvas_w - 2 * pad

    card_bg = blend_rgb(bg_color, text_color, 0.05)
    card_border = blend_rgb(bg_color, text_color, 0.18)
    bar_track = blend_rgb(bg_color, text_color, 0.12)
    muted_text = blend_rgb(bg_color, text_color, 0.65)

    total_books = len(books)
    total_pages = sum(int(b.get("pages", 0)) for b in books)
    avg_pages = int(round(total_pages / total_books)) if total_books else 0

    fic_count = sum(1 for b in books if b.get("category") == "Fiction")
    nonfic_count = total_books - fic_count
    fic_pct = int(round((fic_count / total_books) * 100)) if total_books else 0
    nonfic_pct = 100 - fic_pct

    genre_counts = Counter(b.get("genre", "General") for b in books).most_common(4)

    f_super = get_font(int(20 * scale), bold=True)
    f_title = get_font(int(46 * scale), bold=True)
    f_sec = get_font(int(22 * scale), bold=True)
    f_kpi_num = get_font(int(52 * scale), bold=True)
    f_kpi_lbl = get_font(int(17 * scale), bold=True)
    f_body = get_font(int(21 * scale), bold=False)
    f_body_b = get_font(int(21 * scale), bold=True)
    f_small = get_font(int(16 * scale), bold=True)

    y = pad

    # Header block
    stats_title = header_text.strip() if header_text.strip() else "READING DNA & ANNUAL WRAPPED"
    draw.text((pad, y), "CURATED LITERARY REPORT", fill=accent_rgb, font=f_super)
    y += int(26 * scale)
    draw.text((pad, y), stats_title, fill=txt_rgb, font=f_title)
    y += int(52 * scale)

    footer_reserve = int(55 * scale) if footer_text.strip() else int(15 * scale)
    avail_h = canvas_h - y - pad - footer_reserve
    sec_gap = max(16, int(avail_h * 0.026))

    # 1. KPI Metric Row
    kpi_h = max(100, int(avail_h * 0.15))
    kpi_gap = int(18 * scale)
    kpi_w = (content_w - 2 * kpi_gap) // 3
    kpis = [
        (f"{total_books:,}", "TOTAL TITLES"),
        (f"{total_pages:,}", "PAGES EXPLORED"),
        (f"{avg_pages:,}", "AVG VOLUME SIZE"),
    ]
    for i, (val, label) in enumerate(kpis):
        kx = pad + i * (kpi_w + kpi_gap)
        draw.rounded_rectangle((kx, y, kx + kpi_w, y + kpi_h), radius=int(14 * scale), fill=card_bg, outline=card_border, width=2)
        vb = draw.textbbox((0, 0), val, font=f_kpi_num)
        vw = vb[2] - vb[0]
        draw.text((kx + (kpi_w - vw) // 2, y + int(kpi_h * 0.15)), val, fill=accent_rgb, font=f_kpi_num)
        lb = draw.textbbox((0, 0), label, font=f_kpi_lbl)
        lw = lb[2] - lb[0]
        draw.text((kx + (kpi_w - lw) // 2, y + int(kpi_h * 0.67)), label, fill=muted_text, font=f_kpi_lbl)

    y += kpi_h + sec_gap

    # 2. Hero Editorial AI Analysis Card
    ai_h = max(210, int(avail_h * 0.38))
    draw.rounded_rectangle((pad, y, pad + content_w, y + ai_h), radius=int(18 * scale), fill=card_bg, outline=card_border, width=2)
    inner_x = pad + int(28 * scale)
    inner_w = content_w - 2 * int(28 * scale)

    archetype = ai_analysis.get("archetype", "The Eclectic Synthesizer") if ai_analysis else "The Eclectic Synthesizer"
    draw.text((inner_x, y + int(18 * scale)), "LITERARY ARCHETYPE", fill=accent_rgb, font=f_small)

    f_arch = get_font(int(36 * scale), bold=True)
    draw.text((inner_x, y + int(38 * scale)), f"“{archetype}”", fill=txt_rgb, font=f_arch)

    thesis = (
        ai_analysis.get("thesis", "Navigating nuanced questions of agency, institutional momentum, and speculative horizons across carefully curated worlds.")
        if ai_analysis else "Navigating nuanced questions of agency, institutional momentum, and speculative horizons across carefully curated worlds."
    )

    words = thesis.split()
    lines, curr = [], ""
    for w in words:
        test = (curr + " " + w).strip()
        bb = draw.textbbox((0, 0), test, font=f_body)
        if (bb[2] - bb[0]) < inner_w - 12:
            curr = test
        else:
            lines.append(curr)
            curr = w
    if curr:
        lines.append(curr)

    ty_pos = y + int(90 * scale)
    for ln in lines[:3]:
        draw.text((inner_x, ty_pos), ln, fill=txt_rgb, font=f_body)
        ty_pos += int(28 * scale)

    # Collision & Subconscious Fixation Badges
    fixation = ai_analysis.get("fixation", "Ideology & Systematic Impact") if ai_analysis else "Ideology & Systematic Impact"
    draw.text((inner_x, y + ai_h - int(56 * scale)), f"Subconscious Fixation: {fixation}", fill=accent_rgb, font=f_small)

    if ai_analysis and ai_analysis.get("collision"):
        col_text = f"Thematic Collision: {ai_analysis['collision']}"
        draw.text((inner_x, y + ai_h - int(32 * scale)), col_text[:76] + ("…" if len(col_text) > 76 else ""), fill=muted_text, font=f_small)

    y += ai_h + sec_gap

    # 3. Category Ratio Split
    split_h = max(95, int(avail_h * 0.15))
    draw.rounded_rectangle((pad, y, pad + content_w, y + split_h), radius=int(16 * scale), fill=card_bg, outline=card_border, width=2)
    draw.text((inner_x, y + int(14 * scale)), "PROPORTION MATRIX (FICTION / NON-FICTION)", fill=txt_rgb, font=f_sec)

    bar_y = y + int(46 * scale)
    bar_h = max(18, int(22 * scale))
    draw.rounded_rectangle((inner_x, bar_y, inner_x + inner_w, bar_y + bar_h), radius=bar_h // 2, fill=bar_track)
    if fic_count > 0:
        fic_w = max(bar_h, int(inner_w * (fic_count / total_books)))
        draw.rounded_rectangle((inner_x, bar_y, inner_x + fic_w, bar_y + bar_h), radius=bar_h // 2, fill=accent_rgb)

    draw.text((inner_x, bar_y + bar_h + int(6 * scale)), f"Fiction: {fic_count} ({fic_pct}%)", fill=txt_rgb, font=f_small)
    nb = draw.textbbox((0, 0), f"Non-Fiction: {nonfic_count} ({nonfic_pct}%)", font=f_small)
    draw.text((inner_x + inner_w - (nb[2] - nb[0]), bar_y + bar_h + int(6 * scale)), f"Non-Fiction: {nonfic_count} ({nonfic_pct}%)", fill=muted_text, font=f_small)

    y += split_h + sec_gap

    # 4. Genre Spectrum
    rem_h = max(120, canvas_h - y - pad - footer_reserve)
    draw.rounded_rectangle((pad, y, pad + content_w, y + rem_h), radius=int(16 * scale), fill=card_bg, outline=card_border, width=2)
    draw.text((inner_x, y + int(16 * scale)), "TOP GENRE DOMAINS", fill=txt_rgb, font=f_sec)

    g_start_y = y + int(50 * scale)
    max_g_count = genre_counts[0][1] if genre_counts else 1
    g_step = (rem_h - int(60 * scale)) / max(2, len(genre_counts))

    for idx, (g_name, g_count) in enumerate(genre_counts):
        gy = int(g_start_y + idx * g_step)
        g_pct = int(round((g_count / total_books) * 100))

        draw.text((inner_x, gy), f"{g_name}", fill=txt_rgb, font=f_body_b)
        cb = draw.textbbox((0, 0), f"{g_count} ({g_pct}%)", font=f_body_b)
        draw.text((inner_x + inner_w - (cb[2] - cb[0]), gy), f"{g_count} ({g_pct}%)", fill=accent_rgb, font=f_body_b)

        g_bar_y = gy + int(24 * scale)
        g_bar_h = max(7, int(8 * scale))
        draw.rounded_rectangle((inner_x, g_bar_y, inner_x + inner_w, g_bar_y + g_bar_h), radius=g_bar_h // 2, fill=bar_track)
        fill_w = max(g_bar_h, int(inner_w * (g_count / max_g_count)))
        draw.rounded_rectangle((inner_x, g_bar_y, inner_x + fill_w, g_bar_y + g_bar_h), radius=g_bar_h // 2, fill=accent_rgb)

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) // 2, canvas_h - pad - int(30 * scale)), footer_text, fill=txt_rgb, font=footer_font)

    return canvas


# --- SLIDE 3: PROCEDURAL 3D BOOKSHELF ---
def create_wood_texture(width: int, height: int, base_rgb: tuple, dark_rgb: tuple, vertical: bool = False) -> Image.Image:
    rng = random.Random(101)
    gw = 20 if vertical else max(80, width // 5)
    gh = max(80, height // 5) if vertical else 20

    noise_img = Image.new("RGB", (gw, gh))
    pixels = []
    for idx in range(gw * gh):
        wave = math.sin(idx * 0.17) * 0.12
        t = max(0.0, min(1.0, (rng.random() ** 1.3) + wave))
        r = int(base_rgb[0] * (1 - t * 0.38) + dark_rgb[0] * (t * 0.38))
        g = int(base_rgb[1] * (1 - t * 0.38) + dark_rgb[1] * (t * 0.38))
        b = int(base_rgb[2] * (1 - t * 0.38) + dark_rgb[2] * (t * 0.38))
        pixels.append((r, g, b))
    noise_img.putdata(pixels)

    stretched = noise_img.resize((width, height), Image.Resampling.BICUBIC)
    return stretched.filter(ImageFilter.GaussianBlur(0.7))


def split_into_two_lines(text: str) -> list[str]:
    words = text.split()
    if len(words) <= 2 or len(text) <= 20:
        return [text]
    mid = len(text) // 2
    best_idx = 1
    best_dist = 999
    running = 0
    for i, w in enumerate(words[:-1], 1):
        running += len(w) + 1
        dist = abs(running - mid)
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return [" ".join(words[:best_idx]), " ".join(words[best_idx:])]


def render_spine_typography(
    title: str,
    author: str,
    max_len: int,
    spine_w: int,
    primary_txt: tuple,
    secondary_txt: tuple,
    scale: float,
) -> Image.Image:
    clean_title = title.strip()
    clean_author = author.strip()

    title_lines = split_into_two_lines(clean_title) if (len(clean_title) > 22 and spine_w >= 34) else [clean_title]
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    max_title_sz = min(int(spine_w * (0.35 if len(title_lines) == 2 else 0.46)), int(26 * scale))
    font_sz = max(9, max_title_sz)

    while font_sz >= 9:
        f_title = get_font(font_sz, bold=True)
        f_author = get_font(max(9, int(font_sz * 0.82)), bold=False)

        line_heights, line_widths = [], []
        for line in title_lines:
            tb = dummy_draw.textbbox((0, 0), line, font=f_title)
            line_widths.append(tb[2] - tb[0])
            line_heights.append(tb[3] - tb[1])

        total_stack_h = sum(line_heights) + (4 if len(title_lines) > 1 else 0)
        max_title_w = max(line_widths) if line_widths else 0

        author_w = 0
        if clean_author:
            ab = dummy_draw.textbbox((0, 0), clean_author, font=f_author)
            author_w = (ab[2] - ab[0]) + 18

        if (max_title_w + author_w <= max_len - 12) and (total_stack_h <= spine_w - 6):
            break
        font_sz -= 1

    f_title = get_font(font_sz, bold=True)
    f_author = get_font(max(9, int(font_sz * 0.82)), bold=False)

    txt_layer = Image.new("RGBA", (max(20, max_len), spine_w), (0, 0, 0, 0))
    t_draw = ImageDraw.Draw(txt_layer)

    line_bboxes = [t_draw.textbbox((0, 0), ln, font=f_title) for ln in title_lines]
    max_tw = max((b[2] - b[0]) for b in line_bboxes) if line_bboxes else 0
    line_hs = [(b[3] - b[1]) for b in line_bboxes]
    line_gap = 3 if len(title_lines) > 1 else 0
    total_th = sum(line_hs) + line_gap * (len(title_lines) - 1)

    author_w, author_h = 0, 0
    if clean_author:
        ab = t_draw.textbbox((0, 0), clean_author, font=f_author)
        author_w, author_h = ab[2] - ab[0], ab[3] - ab[1]

    gap_between = 18 if (clean_author and max_tw + author_w + 22 <= max_len) else 10
    total_content_len = max_tw + (gap_between + author_w if clean_author else 0)
    start_x = max(6, (max_len - total_content_len) // 2)

    curr_y = (spine_w - total_th) // 2 - 1
    for ln, l_bbox, lh in zip(title_lines, line_bboxes, line_hs):
        lw = l_bbox[2] - l_bbox[0]
        lx = start_x + (max_tw - lw) // 2
        t_draw.text((lx + 1, curr_y + 1), ln, fill=(0, 0, 0, 165), font=f_title)
        t_draw.text((lx, curr_y), ln, fill=primary_txt, font=f_title)
        curr_y += lh + line_gap

    if clean_author:
        ax = start_x + max_tw + gap_between
        if ax + author_w > max_len - 4:
            ax = max(start_x + max_tw + 6, max_len - author_w - 4)
        ay = (spine_w - author_h) // 2 - 1
        dot_x = start_x + max_tw + (ax - (start_x + max_tw)) // 2
        t_draw.ellipse((dot_x - 2, spine_w // 2 - 2, dot_x + 2, spine_w // 2 + 2), fill=secondary_txt)
        t_draw.text((ax + 1, ay + 1), clean_author, fill=(0, 0, 0, 150), font=f_author)
        t_draw.text((ax, ay), clean_author, fill=secondary_txt, font=f_author)

    return txt_layer.rotate(270, expand=True)


def render_realistic_spine(book: dict, spine_w: int, spine_h: int, scale: float) -> Image.Image:
    spine_hex = book.get("spine_color") or extract_dominant_color(book["image"])
    r_base, g_base, b_base = hex_to_rgb(spine_hex)

    crown_h = max(5, int(7 * scale))
    jacket_h = spine_h - crown_h

    full_book_img = Image.new("RGBA", (spine_w, spine_h), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(full_book_img)

    board_col = (max(20, r_base - 25), max(20, g_base - 25), max(20, b_base - 25), 255)
    b_draw.rectangle((0, 0, 3, crown_h + 2), fill=board_col)
    b_draw.rectangle((spine_w - 4, 0, spine_w - 1, crown_h + 2), fill=board_col)
    b_draw.rectangle((3, 2, spine_w - 4, crown_h + 2), fill=(232, 224, 205, 255))
    for py in range(3, crown_h + 1, 2):
        b_draw.line([(4, py), (spine_w - 5, py)], fill=(205, 195, 175, 180), width=1)
    b_draw.rectangle((4, crown_h - 2, spine_w - 5, crown_h + 1), fill=(185, 55, 45, 220))

    cov_wrapped = ImageOps.fit(book["image"].convert("RGB"), (spine_w, jacket_h), Image.Resampling.LANCZOS)
    cov_soft = cov_wrapped.filter(ImageFilter.GaussianBlur(1.4))
    solid_tint = Image.new("RGB", (spine_w, jacket_h), (r_base, g_base, b_base))
    jacket_rgb = Image.blend(cov_soft, solid_tint, 0.45)

    lighting_strip = Image.new("L", (spine_w, 1))
    hinge_l = max(3, int(spine_w * 0.08))
    hinge_r = min(spine_w - 3, max(hinge_l + 4, int(spine_w * 0.92)))
    l_vals = []
    for x in range(spine_w):
        nx = x / max(1, spine_w - 1)
        if x in (hinge_l, hinge_r):
            val = 88
        elif x == hinge_l + 1:
            val = 172
        else:
            curve = math.sin(nx * math.pi)
            specular = math.exp(-((nx - 0.28) ** 2) / 0.04) * 42
            right_roll = (nx ** 1.7) * 62
            val = int(max(58, min(205, 118 + curve * 24 + specular - right_roll)))
        l_vals.append(val)
    lighting_strip.putdata(l_vals)
    lighting_map = lighting_strip.resize((spine_w, jacket_h), Image.Resampling.BILINEAR)

    lit_jacket = ImageChops.multiply(jacket_rgb, lighting_map.convert("RGB"))
    lit_jacket = ImageEnhance.Brightness(lit_jacket).enhance(1.40)
    jacket_rgba = lit_jacket.convert("RGBA")
    j_draw = ImageDraw.Draw(jacket_rgba)

    stat_sample = lit_jacket.resize((1, 1), Image.Resampling.BILINEAR).getpixel((0, 0))
    avg_lum = 0.299 * stat_sample[0] + 0.587 * stat_sample[1] + 0.114 * stat_sample[2]
    if avg_lum > 140:
        j_draw.rounded_rectangle((4, int(jacket_h * 0.05), spine_w - 5, int(jacket_h * 0.95)), radius=4, fill=(255, 252, 245, 115))
        primary_txt = (24, 20, 18, 252)
        secondary_txt = (55, 48, 42, 230)
    else:
        j_draw.rounded_rectangle((4, int(jacket_h * 0.05), spine_w - 5, int(jacket_h * 0.95)), radius=4, fill=(12, 10, 10, 115))
        primary_txt = (252, 248, 238, 252)
        secondary_txt = (232, 218, 190, 230)

    band_y_top = int(jacket_h * 0.05)
    band_y_bot = int(jacket_h * 0.94)
    j_draw.line([(3, band_y_top), (spine_w - 4, band_y_top)], fill=secondary_txt, width=2)
    j_draw.line([(3, band_y_bot), (spine_w - 4, band_y_bot)], fill=secondary_txt, width=2)

    text_avail_len = band_y_bot - band_y_top - 16
    txt_img = render_spine_typography(
        title=book["title"],
        author=book.get("author", ""),
        max_len=text_avail_len,
        spine_w=spine_w,
        primary_txt=primary_txt,
        secondary_txt=secondary_txt,
        scale=scale,
    )
    jacket_rgba.alpha_composite(txt_img, (0, band_y_top + 8))
    full_book_img.alpha_composite(jacket_rgba, (0, crown_h))
    return full_book_img


def generate_bookshelf_image(
    books: list,
    canvas_size: tuple[int, int],
    margin: int,
    bg_color: str,
    text_color: str,
    shelf_theme_name: str,
    shelf_rows: int,
    header_text: str,
    footer_text: str,
) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    canvas = Image.new("RGBA", (canvas_w, canvas_h), hex_to_rgba(bg_color, 255))
    draw = ImageDraw.Draw(canvas)

    n_books = len(books)
    if n_books == 0:
        return canvas.convert("RGB")

    theme = SHELF_THEMES.get(shelf_theme_name, SHELF_THEMES["Warm Oak"])
    scale = min(canvas_w / 1080.0, canvas_h / 1080.0)
    pad = max(36, int(margin * 0.85))
    txt_rgb = hex_to_rgb(text_color)

    y_top = pad
    if header_text.strip():
        f_title = get_font(int(48 * scale), bold=True)
        bbox = draw.textbbox((0, 0), header_text, font=f_title)
        draw.text(((canvas_w - (bbox[2] - bbox[0])) / 2, y_top), header_text, fill=txt_rgb, font=f_title)
        y_top += (bbox[3] - bbox[1]) + int(28 * scale)

    footer_reserve = int(60 * scale) if footer_text.strip() else int(10 * scale)
    case_x, case_y = pad, y_top
    case_w = canvas_w - 2 * pad
    case_h = canvas_h - case_y - pad - footer_reserve

    frame_thick = max(22, int(28 * scale))
    plank_thick = max(22, int(28 * scale))

    frame_tex = create_wood_texture(case_w, case_h, theme["frame"], theme["grain_dark"], vertical=True)
    canvas.alpha_composite(add_rounded_corners(frame_tex, int(14 * scale)), (case_x, case_y))

    inner_x = case_x + frame_thick
    inner_y = case_y + frame_thick
    inner_w = case_w - 2 * frame_thick
    inner_h = case_h - 2 * frame_thick

    back_tex = create_wood_texture(inner_w, inner_h, theme["back"], theme["grain_dark"], vertical=True).convert("RGBA")
    canvas.alpha_composite(back_tex, (inner_x, inner_y))

    ledge_depth = max(8, int(10 * scale))
    plank_total_h = plank_thick + ledge_depth
    plank_tex = Image.new("RGBA", (inner_w, plank_total_h), (0, 0, 0, 0))
    top_ledge = create_wood_texture(inner_w, ledge_depth, theme["frame"], theme["grain_dark"], vertical=False).convert("RGBA")
    plank_tex.alpha_composite(top_ledge, (0, 0))
    front_face = create_wood_texture(inner_w, plank_thick, theme["plank"], theme["grain_dark"], vertical=False).convert("RGBA")
    plank_tex.alpha_composite(front_face, (0, ledge_depth))

    n_shelves = max(1, min(shelf_rows, n_books))
    books_per_shelf = math.ceil(n_books / n_shelves)
    shelf_allowance_h = inner_h / n_shelves

    for s_idx in range(n_shelves):
        bay_top = int(inner_y + s_idx * shelf_allowance_h)
        bay_bottom = int(inner_y + (s_idx + 1) * shelf_allowance_h)
        plank_y = bay_bottom - plank_total_h
        book_rest_y = plank_y + ledge_depth
        clearance_h = book_rest_y - bay_top

        canvas.alpha_composite(plank_tex, (inner_x, plank_y))
        shelf_books = books[s_idx * books_per_shelf : (s_idx + 1) * books_per_shelf]
        if shelf_books:
            rel_widths = [0.72 + 0.75 * ((max(140, min(850, int(b.get("pages", 320)))) - 140) / 710.0) for b in shelf_books]
            base_unit_w = max(30, min(int(inner_w * 0.13), int((inner_w * 0.88) / max(1.0, sum(rel_widths)))))
            pixel_widths = [max(28, int(rw * base_unit_w)) for rw in rel_widths]
            total_row_w = sum(pixel_widths)
            if total_row_w > inner_w - 28:
                shrink = (inner_w - 28) / total_row_w
                pixel_widths = [max(22, int(pw * shrink)) for pw in pixel_widths]
                total_row_w = sum(pixel_widths)

            curr_x = inner_x + max(22, (inner_w - total_row_w) // 2)
            for book, spine_w in zip(shelf_books, pixel_widths):
                h_seed = int(hashlib.md5(book["title"].encode("utf-8")).hexdigest()[:4], 16)
                spine_h = max(65, int(clearance_h * (0.81 + (h_seed % 13) * 0.01)))
                spine_y = book_rest_y - spine_h + (h_seed % 4)

                spine_img = render_realistic_spine(book, spine_w, spine_h, scale)
                canvas.alpha_composite(spine_img, (curr_x, spine_y))
                curr_x += spine_w + 1

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) // 2, canvas_h - pad - int(32 * scale)), footer_text, fill=txt_rgb, font=footer_font)

    return canvas.convert("RGB")


def add_book_entry(meta: dict, custom_img: Image.Image | None = None):
    img = custom_img.convert("RGB") if custom_img is not None else (
        Image.open(io.BytesIO(meta["img_bytes"])).convert("RGB") if meta.get("img_bytes") else create_placeholder_cover(meta["title"], meta["author"])
    )
    found = custom_img is not None or bool(meta.get("img_bytes"))

    st.session_state.books.append({
        "id": st.session_state.next_id,
        "title": meta["title"],
        "author": meta["author"],
        "image": img,
        "found": found,
        "genre": meta.get("genre", "General Fiction"),
        "category": meta.get("category", "Fiction"),
        "year": int(meta.get("year", 2024)),
        "pages": int(meta.get("pages", 320)),
        "spine_color": extract_dominant_color(img),
    })
    st.session_state.next_id += 1
    st.session_state.ai_stats_cache = None
    st.session_state.ai_shelf_cache = None


# --- UI LAYOUT ---
st.title("📚 Social Media Book Collage, AI Stats & Bookshelf Maker")
st.markdown("Enter books you've read to generate **Cover Collages**, **AI Reading Reports**, and **Bookshelves**.")

col_left, col_right = st.columns([1.08, 1.22], gap="large")

with col_left:
    st.subheader("1. Add Your Books")
    tab_bulk, tab_single, tab_upload = st.tabs(["📝 Paste Book List", "🔍 Add Single Book", "🖼 Add Manual Book"])

    with tab_bulk:
        bulk_input = st.text_area(
            "Enter one book per line (Title & Author recommended):",
            placeholder="Head North by Andy Burnham\nProject Hail Mary by Andy Weir\nTomorrow, and Tomorrow, and Tomorrow",
            height=140,
        )
        if st.button("✨ Fetch Covers & Stats", type="primary", width="stretch"):
            lines = [line.strip() for line in bulk_input.split("\n") if line.strip()]
            if lines:
                progress = st.progress(0, text="Fetching exact book metadata...")
                for i, line in enumerate(lines):
                    meta = fetch_book_data(line, gb_api_key=google_books_key)
                    add_book_entry(meta)
                    progress.progress((i + 1) / len(lines), text=f"Loaded: {meta['title']}")
                progress.empty()
                st.rerun()

    with tab_single:
        single_query = st.text_input("Book Title / Author", placeholder="e.g., Head North by Andy Burnham")
        if st.button("Add Book", width="stretch") and single_query.strip():
            with st.spinner("Looking up book..."):
                meta = fetch_book_data(single_query.strip(), gb_api_key=google_books_key)
                add_book_entry(meta)
                st.rerun()

    with tab_upload:
        m_col1, m_col2 = st.columns(2)
        custom_title = m_col1.text_input("Book Title", placeholder="Title")
        custom_author = m_col2.text_input("Author", placeholder="Author")
        m_col3, m_col4, m_col5 = st.columns(3)
        custom_cat = m_col3.selectbox("Type", ["Fiction", "Non-Fiction"])
        custom_genre = m_col4.text_input("Genre", value="Literary Fiction")
        custom_pages = m_col5.number_input("Pages", min_value=1, max_value=5000, value=320)
        custom_year = st.number_input("Publication Year", min_value=1000, max_value=2030, value=2024)
        uploaded_file = st.file_uploader("Upload Cover Image", type=["jpg", "jpeg", "png", "webp"])

        if st.button("Add Manual Book", width="stretch") and (custom_title or uploaded_file):
            custom_img = Image.open(uploaded_file) if uploaded_file else None
            meta = {
                "title": custom_title or (uploaded_file.name if uploaded_file else "Untitled"),
                "author": custom_author,
                "img_bytes": None,
                "genre": custom_genre,
                "category": custom_cat,
                "year": custom_year,
                "pages": custom_pages,
            }
            add_book_entry(meta, custom_img=custom_img)
            st.rerun()

    # --- BOOK MANAGEMENT & ACCURATE STATS COPYING ---
    if st.session_state.books:
        st.divider()
        h_col1, h_col2 = st.columns([3, 1])
        h_col1.markdown(f"**Current Books ({len(st.session_state.books)})**")
        if h_col2.button("🗑️ Clear All"):
            st.session_state.books = []
            st.session_state.cover_search_results = {}
            st.session_state.ai_stats_cache = None
            st.session_state.ai_shelf_cache = None
            st.rerun()

        for i, b in enumerate(st.session_state.books):
            book_id = b["id"]
            exp_label = f"📖 #{i + 1}: {b['title']}" + ("" if b.get("found", True) else " ⚠ (Needs Cover)")

            with st.expander(exp_label, expanded=not b.get("found", True)):
                top_c1, top_c2 = st.columns([1, 3.2])
                top_c1.image(b["image"], width=95, caption="Cover")

                with top_c2:
                    e_col1, e_col2 = st.columns(2)
                    b["title"] = e_col1.text_input("Title", value=b["title"], key=f"t_{book_id}")
                    b["author"] = e_col2.text_input("Author", value=b["author"], key=f"a_{book_id}")

                    replacement_file = st.file_uploader("📤 Upload Cover", type=["jpg", "jpeg", "png", "webp"], key=f"rep_cov_{book_id}")
                    if replacement_file is not None:
                        file_sig = f"cov_{replacement_file.name}_{replacement_file.size}"
                        if st.session_state.processed_uploads.get(book_id) != file_sig:
                            new_img = Image.open(io.BytesIO(replacement_file.getvalue())).convert("RGB")
                            b["image"] = new_img
                            b["spine_color"] = extract_dominant_color(new_img)
                            b["found"] = True
                            st.session_state.processed_uploads[book_id] = file_sig
                            st.session_state.ai_stats_cache = None
                            st.rerun()

                # Search & Copy All Stats Correctly
                st.markdown("**🔎 Lookup & Copy Cover + Metadata:**")
                lk_c1, lk_c2 = st.columns([3, 1.4])
                manual_q = lk_c1.text_input("Search query", value=f"{b['title']} {b['author']}".strip(), key=f"mq_{book_id}", label_visibility="collapsed")
                if lk_c2.button("🔍 Search", key=f"btn_mq_{book_id}", width="stretch"):
                    with st.spinner("Searching editions..."):
                        st.session_state.cover_search_results[book_id] = search_cover_candidates_with_stats(manual_q, gb_api_key=google_books_key)

                if book_id in st.session_state.cover_search_results:
                    cands = st.session_state.cover_search_results[book_id]
                    if not cands:
                        st.info("No editions found.")
                    else:
                        cand_cols = st.columns(min(3, len(cands)))
                        for c_idx, cand in enumerate(cands):
                            with cand_cols[c_idx % len(cand_cols)]:
                                st.image(cand["img_bytes"], width=90)
                                st.markdown(f"**{cand['title'][:22]}**\n<small>{cand['author']}\n{cand['genre']} • {cand['pages']}p ({cand['year']})</small>", unsafe_allow_html=True)
                                if st.button("Use Match", key=f"pick_{book_id}_{c_idx}", width="stretch"):
                                    picked_img = Image.open(io.BytesIO(cand["img_bytes"])).convert("RGB")
                                    b["image"] = picked_img
                                    b["spine_color"] = extract_dominant_color(picked_img)
                                    b["found"] = True
                                    b["title"] = cand["title"]
                                    if cand["author"]:
                                        b["author"] = cand["author"]
                                    b["pages"] = cand["pages"]
                                    b["year"] = cand["year"]
                                    b["genre"] = cand["genre"]
                                    b["category"] = cand["category"]

                                    # Directly update Streamlit widget state
                                    st.session_state[f"t_{book_id}"] = cand["title"]
                                    st.session_state[f"a_{book_id}"] = cand["author"]
                                    st.session_state[f"p_{book_id}"] = cand["pages"]
                                    st.session_state[f"y_{book_id}"] = cand["year"]
                                    st.session_state[f"g_{book_id}"] = cand["genre"]
                                    st.session_state[f"cat_{book_id}"] = cand["category"]

                                    del st.session_state.cover_search_results[book_id]
                                    st.session_state.ai_stats_cache = None
                                    st.session_state.ai_shelf_cache = None
                                    st.rerun()

                st.divider()
                s_c1, s_c2, s_c3, s_c4, s_c5 = st.columns([1.3, 1.4, 0.9, 0.9, 0.8])
                b["category"] = s_c1.selectbox("Category", ["Fiction", "Non-Fiction"], index=0 if b.get("category") == "Fiction" else 1, key=f"cat_{book_id}")
                b["genre"] = s_c2.text_input("Genre", value=b.get("genre", "Fiction"), key=f"g_{book_id}")
                b["pages"] = s_c3.number_input("Pages", min_value=1, max_value=9999, value=int(b.get("pages", 320)), key=f"p_{book_id}")
                b["year"] = s_c4.number_input("Year", min_value=1000, max_value=2035, value=int(b.get("year", 2024)), key=f"y_{book_id}")
                b["spine_color"] = s_c5.color_picker("Spine", value=b.get("spine_color", "#4A6151"), key=f"sp_{book_id}")

                if st.button("🗑️ Remove Book", key=f"del_{book_id}"):
                    st.session_state.books.pop(i)
                    st.session_state.ai_stats_cache = None
                    st.session_state.ai_shelf_cache = None
                    st.rerun()

    st.divider()
    st.subheader("2. Customize Style & Layout")

    preset = st.selectbox(
        "Social Media Format",
        [
            "Instagram Story / TikTok (1080 x 1920)",
            "Instagram Portrait Post (1080 x 1350)",
            "Instagram Square Post (1080 x 1080)",
            "X / Twitter Landscape (1600 x 900)",
        ],
    )

    preset_dims = {
        "Instagram Story / TikTok (1080 x 1920)": (1080, 1920),
        "Instagram Portrait Post (1080 x 1350)": (1080, 1350),
        "Instagram Square Post (1080 x 1080)": (1080, 1080),
        "X / Twitter Landscape (1600 x 900)": (1600, 900),
    }
    canvas_size = preset_dims[preset]

    n_books = max(1, len(st.session_state.books))
    default_cols = min(6, max(1, int(math.ceil(math.sqrt(n_books)))))
    default_shelves = min(5, max(1, math.ceil(n_books / 8)))

    s_col1, s_col2 = st.columns(2)
    cols = s_col1.slider("Collage Columns", min_value=1, max_value=8, value=default_cols)
    gap = s_col2.slider("Spacing Between Covers", min_value=0, max_value=80, value=28)

    s_col3, s_col4 = st.columns(2)
    margin = s_col3.slider("Outer Margin", min_value=20, max_value=180, value=70)
    corner_radius = s_col4.slider("Cover Corner Rounding", min_value=0, max_value=40, value=12)

    sh_col1, sh_col2 = st.columns(2)
    shelf_theme_name = sh_col1.selectbox("Bookcase Wood", list(SHELF_THEMES.keys()))
    shelf_render_mode = sh_col2.selectbox(
        "Bookshelf Style",
        ["AI Studio Photograph (Photorealistic)", "Procedural 3D Bookshelf (Instant)"],
    )

    t_col1, t_col2 = st.columns(2)
    header_text = t_col1.text_input("Header Title (Optional)", placeholder="e.g., 2026 Reading Journey")
    footer_text = t_col2.text_input("Footer Handle (Optional)", placeholder="e.g., @curatedreader")

    c_col1, c_col2, c_col3, c_col4 = st.columns(4)
    bg_color = c_col1.color_picker("Background", "#F4F1EA")
    text_color = c_col2.color_picker("Text Color", "#221E1C")
    accent_color = c_col3.color_picker("Editorial Accent", "#B85C38")
    add_shadow = c_col4.checkbox("3D Shadow", value=True)

with col_right:
    st.subheader("3. Preview & Export All 3 Slides")

    if not st.session_state.books:
        st.info("👈 Add books on the left to generate your three slides!")
    else:
        # Run AI Deep Literary Critique for Slide 2
        if st.session_state.ai_stats_cache is None and (gemini_key or groq_key):
            with st.spinner("🧠 AI Literary Critic analyzing your reading patterns..."):
                st.session_state.ai_stats_cache = generate_ai_stats_analysis(
                    st.session_state.books, gemini_api_key=gemini_key, groq_api_key=groq_key
                )

        collage_img = generate_collage(
            books=st.session_state.books,
            canvas_size=canvas_size,
            cols=cols,
            gap=gap,
            margin=margin,
            bg_color=bg_color,
            corner_radius=corner_radius,
            add_shadow=add_shadow,
            header_text=header_text,
            footer_text=footer_text,
            text_color=text_color,
        )

        stats_img = generate_stats_image(
            books=st.session_state.books,
            canvas_size=canvas_size,
            margin=margin,
            bg_color=bg_color,
            text_color=text_color,
            accent_color=accent_color,
            header_text=header_text,
            footer_text=footer_text,
            ai_analysis=st.session_state.ai_stats_cache,
        )

        # Slide 3: AI Photorealistic vs Procedural Bookshelf
        if shelf_render_mode == "AI Studio Photograph (Photorealistic)":
            if st.session_state.ai_shelf_cache is None:
                with st.spinner("📸 Rendering photorealistic studio bookshelf..."):
                    ai_shelf_img, err = generate_ai_photorealistic_bookshelf(
                        st.session_state.books,
                        wood_style=shelf_theme_name,
                        gemini_api_key=gemini_key,
                        aspect_ratio=preset,
                    )
                    if ai_shelf_img:
                        st.session_state.ai_shelf_cache = ai_shelf_img
                    else:
                        st.warning(f"Notice: {err}. Showing procedural 3D shelf preview.")

            shelf_img = st.session_state.ai_shelf_cache or generate_bookshelf_image(
                books=st.session_state.books,
                canvas_size=canvas_size,
                margin=margin,
                bg_color=bg_color,
                text_color=text_color,
                shelf_theme_name=shelf_theme_name,
                shelf_rows=default_shelves,
                header_text=header_text,
                footer_text=footer_text,
            )
        else:
            shelf_img = generate_bookshelf_image(
                books=st.session_state.books,
                canvas_size=canvas_size,
                margin=margin,
                bg_color=bg_color,
                text_color=text_color,
                shelf_theme_name=shelf_theme_name,
                shelf_rows=default_shelves,
                header_text=header_text,
                footer_text=footer_text,
            )

        buf_collage, buf_stats, buf_shelf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        collage_img.save(buf_collage, format="PNG", quality=95)
        stats_img.save(buf_stats, format="PNG", quality=95)
        shelf_img.save(buf_shelf, format="PNG", quality=95)

        dl_col1, dl_col2, dl_col3 = st.columns(3)
        dl_col1.download_button(label="📥 Slide 1: Collage", data=buf_collage.getvalue(), file_name="slide1_collage.png", mime="image/png", width="stretch")
        dl_col2.download_button(label="📊 Slide 2: AI Stats", data=buf_stats.getvalue(), file_name="slide2_reading_dna.png", mime="image/png", width="stretch")
        dl_col3.download_button(label="🪵 Slide 3: Bookshelf", data=buf_shelf.getvalue(), file_name="slide3_bookshelf.png", mime="image/png", width="stretch")

        tab_preview1, tab_preview2, tab_preview3 = st.tabs(["🖼️ Slide 1: Cover Collage", "📊 Slide 2: Reading DNA", "🪵 Slide 3: Bookshelf"])
        with tab_preview1:
            st.image(collage_img, width="stretch")
        with tab_preview2:
            st.image(stats_img, width="stretch")
            if st.button("🔄 Re-Analyze Reading DNA with AI"):
                st.session_state.ai_stats_cache = None
                st.rerun()
        with tab_preview3:
            st.image(shelf_img, width="stretch")
            if shelf_render_mode == "AI Studio Photograph (Photorealistic)":
                if st.button("🔄 Regenerate AI Studio Bookshelf"):
                    st.session_state.ai_shelf_cache = None
                    st.rerun()
