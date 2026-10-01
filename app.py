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
    st.header("🔑 Free AI Key Setup")
    st.caption(
        "Add your free **Google Gemini** or **Groq** API key to unlock AI analysis, "
        "photorealistic shelf generation, and metadata matching."
    )

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
            help="Free key at https://aistudio.google.com/apikey",
        )
        st.markdown("👉 [Get a Free Gemini Key](https://aistudio.google.com/apikey)")
    elif ai_provider == "Groq Cloud (Free Tier)":
        groq_key = st.text_input(
            "Groq API Key",
            value=get_secret_or_default("GROQ_API_KEY"),
            type="password",
            placeholder="gsk_...",
            help="Free key (no card) at https://console.groq.com/keys",
        )
        st.markdown("👉 [Get a Free Groq Key](https://console.groq.com/keys)")

    st.divider()
    google_books_key = st.text_input(
        "Google Books API Key (Optional)",
        value=get_secret_or_default("GOOGLE_BOOKS_API_KEY"),
        type="password",
        help="Optional: prevents Google Books rate limits on Streamlit Cloud.",
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
        counts = Counter(list(quantized.getdata()))

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

        if best_score < 0:
            best_rgb = counts.most_common(1)[0][0]
        return "#{:02x}{:02x}{:02x}".format(*best_rgb)
    except Exception:
        return "#4A6151"


# --- AI HELPERS: GEMINI & GROQ ---
def resolve_book_with_ai(raw_query: str, gemini_api_key: str = "", groq_api_key: str = "") -> dict | None:
    if not gemini_api_key and not groq_api_key:
        return None

    prompt = (
        f"You are an expert librarian. The user entered this book: '{raw_query}'.\n"
        "Return ONLY a valid JSON object with these keys:\n"
        "{\n"
        '  "title": "Exact book title",\n'
        '  "author": "Primary author",\n'
        '  "isbn13": "13-digit ISBN (digits only, or empty string)",\n'
        '  "category": "Fiction" or "Non-Fiction",\n'
        '  "genre": "Short 1-3 word genre",\n'
        '  "year": 2024,\n'
        '  "pages": 320\n'
        "}"
    )

    if gemini_api_key:
        for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
                }
                resp = requests.post(
                    url,
                    headers={"x-goog-api-key": gemini_api_key.strip(), "Content-Type": "application/json"},
                    json=payload,
                    timeout=9,
                )
                if resp.status_code == 200:
                    text_out = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_out)
                    if isinstance(parsed, dict) and parsed.get("title"):
                        return parsed
            except Exception:
                continue

    if groq_api_key:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You output only valid JSON objects."},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            }
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {groq_api_key.strip()}", "Content-Type": "application/json"},
                json=payload,
                timeout=9,
            )
            if resp.status_code == 200:
                text_out = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(text_out)
                if isinstance(parsed, dict) and parsed.get("title"):
                    return parsed
        except Exception:
            pass

    return None


def generate_ai_stats_analysis(books: list, gemini_api_key: str = "", groq_api_key: str = "") -> dict | None:
    """Uses Gemini or Groq to analyze the user's reading list like an expert literary critic."""
    if not books or (not gemini_api_key and not groq_api_key):
        return None

    book_list_str = "\n".join(
        [f"- {b['title']} by {b.get('author','')} ({b.get('genre','')}, {b.get('category','')})" for b in books]
    )

    prompt = (
        "You are an insightful literary critic analyzing a reader's reading list.\n"
        f"Here are the books they read:\n{book_list_str}\n\n"
        "Return ONLY a valid JSON object with these exact keys:\n"
        "{\n"
        '  "persona": "A 2-4 word witty/evocative persona title (e.g., \'The Pragmatic Philosopher\', \'Sci-Fi Political Realist\')",\n'
        '  "critique": "A sharp, engaging 2-sentence summary of what their reading taste reveals about their worldview and curiosity.",\n'
        '  "pairing": "Two books from the list that unexpectedly complement each other, with a 1-sentence explanation of why.",\n'
        '  "vibe_tags": ["Tag1", "Tag2", "Tag3", "Tag4"]\n'
        "}"
    )

    if gemini_api_key:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
            }
            resp = requests.post(
                url,
                headers={"x-goog-api-key": gemini_api_key.strip(), "Content-Type": "application/json"},
                json=payload,
                timeout=12,
            )
            if resp.status_code == 200:
                return json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
        except Exception:
            pass

    if groq_api_key:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You output only valid JSON objects."},
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
                return json.loads(resp.json()["choices"][0]["message"]["content"])
        except Exception:
            pass

    return None


def generate_ai_photorealistic_bookshelf(
    books: list,
    wood_style: str,
    gemini_api_key: str,
    aspect_ratio: str = "4:5",
) -> Image.Image | None:
    """
    Calls Google's free Gemini 2.5 Flash Image model to generate a studio-grade,
    photorealistic photo of the user's books on a physical wooden shelf.
    """
    if not gemini_api_key or not books:
        return None

    book_titles = ", ".join([f"'{b['title']}' by {b.get('author','')}" for b in books[:18]])

    prompt = (
        f"A crisp, award-winning studio photograph of a physical {wood_style} wooden bookcase shelf. "
        f"Standing neatly on the shelf are physical hardcover and paperback book spines with legible embossed title text for: {book_titles}. "
        "The books have realistic cloth, paper, and matte dust-jacket textures with slight natural variations in height, thickness, and colors. "
        "Soft cinematic lighting, shallow depth of field, natural wood grain on the shelf plank, ambient studio shadows, high-end editorial photography."
    )

    ar_map = {
        "Instagram Story / TikTok (1080 x 1920)": "9:16",
        "Instagram Portrait Post (1080 x 1350)": "4:5",
        "Instagram Square Post (1080 x 1080)": "1:1",
        "X / Twitter Landscape (1600 x 900)": "16:9",
    }
    target_ar = ar_map.get(aspect_ratio, "4:5")

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={gemini_api_key.strip()}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "aspectRatio": target_ar,
            },
        }
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
        if resp.status_code == 200:
            for part in resp.json()["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    b64_bytes = base64.b64decode(part["inlineData"]["data"])
                    return Image.open(io.BytesIO(b64_bytes)).convert("RGB")
    except Exception:
        pass

    return None


# --- SEARCH & VERIFICATION HELPERS ---
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
    clean_genre = genre_map.get(clean_genre, clean_genre)
    return clean_genre, category


def fetch_book_data(
    raw_query: str,
    gemini_api_key: str = "",
    groq_api_key: str = "",
    gb_api_key: str = "",
) -> dict:
    cache_key = f"bm_v7_{raw_query.strip().lower()}_{bool(gemini_api_key or groq_api_key)}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    req_title, req_author = parse_title_author(raw_query)
    ai_meta = resolve_book_with_ai(raw_query, gemini_api_key=gemini_api_key, groq_api_key=groq_api_key)

    isbn13 = ""
    if ai_meta:
        req_title = ai_meta.get("title") or req_title
        req_author = ai_meta.get("author") or req_author
        isbn13 = re.sub(r"[^0-9X]", "", str(ai_meta.get("isbn13", "")))

    exact_search = f"{req_title} {req_author}".strip()
    candidates = []
    img_bytes = None

    if len(isbn13) in (10, 13):
        ol_isbn_url = f"https://covers.openlibrary.org/b/isbn/{isbn13}-L.jpg"
        img_bytes = download_valid_image(ol_isbn_url)

    # Search Google Books
    for gb_query in (exact_search, raw_query.strip()):
        try:
            gb_params = {"q": gb_query, "maxResults": 6}
            if gb_api_key:
                gb_params["key"] = gb_api_key.strip()
            resp = requests.get(
                "https://www.googleapis.com/books/v1/volumes",
                params=gb_params,
                headers=HEADERS,
                timeout=7,
            )
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

    # Search Open Library
    ol_queries = []
    if req_author:
        ol_queries.append({"title": req_title, "author": req_author})
    ol_queries.append({"q": exact_search})

    for ol_q in ol_queries:
        try:
            params = {
                **ol_q,
                "fields": "title,author_name,cover_i,first_publish_year,number_of_pages_median,subject",
                "limit": 6,
            }
            resp = requests.get("https://openlibrary.org/search.json", params=params, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                for doc in resp.json().get("docs", []):
                    c_title = doc.get("title", "")
                    c_authors = doc.get("author_name", [""])
                    c_author = ", ".join(c_authors)
                    score = verify_exact_match(req_title, req_author, c_title, c_author)
                    if score > 0:
                        cov_id = doc.get("cover_i")
                        cov_url = f"https://covers.openlibrary.org/b/id/{cov_id}-L.jpg" if cov_id else ""
                        candidates.append({
                            "score": score + (0.08 if cov_url else 0.0),
                            "title": c_title,
                            "author": c_authors[0] if c_authors else "",
                            "cover_url": cov_url,
                            "fallback_url": "",
                            "primary_genre": "",
                            "subjects": doc.get("subject", [])[:12],
                            "year": int(doc["first_publish_year"]) if doc.get("first_publish_year") else None,
                            "pages": int(doc["number_of_pages_median"]) if doc.get("number_of_pages_median") else None,
                        })
        except Exception:
            pass

    # Search Apple Books UK & US
    for country in ("GB", "US"):
        for entity in ("ebook", "audiobook"):
            try:
                resp = requests.get(
                    "https://itunes.apple.com/search",
                    params={"term": exact_search, "country": country, "entity": entity, "limit": 5},
                    headers=HEADERS,
                    timeout=6,
                )
                if resp.status_code == 200:
                    for item in resp.json().get("results", []):
                        c_title = item.get("trackName") or item.get("collectionName") or ""
                        c_author = item.get("artistName", "")
                        score = verify_exact_match(req_title, req_author, c_title, c_author)
                        if score > 0:
                            art_url = item.get("artworkUrl100", "")
                            hd_url = re.sub(r"100x100bb", "800x800bb", art_url) if art_url else ""
                            rel_date = item.get("releaseDate", "")
                            yr = int(rel_date[:4]) if (len(rel_date) >= 4 and rel_date[:4].isdigit()) else None
                            candidates.append({
                                "score": score + (0.06 if entity == "ebook" else 0.02),
                                "title": re.sub(r"\s*\(Unabridged\)\s*", "", c_title, flags=re.IGNORECASE).strip(),
                                "author": c_author,
                                "cover_url": hd_url,
                                "fallback_url": art_url,
                                "primary_genre": item.get("primaryGenreName", ""),
                                "subjects": item.get("genres", []),
                                "year": yr,
                                "pages": None,
                            })
            except Exception:
                pass

    candidates.sort(key=lambda x: x["score"], reverse=True)

    display_title = req_title.title() if req_title.islower() else req_title
    display_author = req_author.title() if req_author.islower() else req_author

    primary_genre = ai_meta.get("genre", "") if ai_meta else ""
    subjects = []
    year = int(ai_meta["year"]) if (ai_meta and str(ai_meta.get("year", "")).isdigit()) else None
    pages = int(ai_meta["pages"]) if (ai_meta and str(ai_meta.get("pages", "")).isdigit()) else None

    if candidates and not display_author and candidates[0]["author"]:
        display_author = candidates[0]["author"]

    for cand in candidates:
        if img_bytes is None and cand["cover_url"]:
            img_bytes = download_valid_image(cand["cover_url"])
            if img_bytes is None and cand.get("fallback_url"):
                img_bytes = download_valid_image(cand["fallback_url"])
        if not pages and cand["pages"]:
            pages = cand["pages"]
        if not year and cand["year"]:
            year = cand["year"]
        if not primary_genre and cand["primary_genre"]:
            primary_genre = cand["primary_genre"]
        if cand["subjects"]:
            subjects.extend(cand["subjects"])

    clean_genre, category = classify_fiction_nonfiction(primary_genre, subjects)
    if ai_meta and ai_meta.get("category") in ("Fiction", "Non-Fiction"):
        category = ai_meta["category"]
    if ai_meta and ai_meta.get("genre"):
        clean_genre = ai_meta["genre"]

    data = {
        "title": display_title,
        "author": display_author,
        "img_bytes": img_bytes,
        "genre": clean_genre,
        "category": category,
        "year": year if year else 2024,
        "pages": pages if pages else 320,
    }
    if img_bytes is not None:
        st.session_state[cache_key] = data
    return data


def search_cover_candidates_with_stats(query: str, gb_api_key: str = "", max_results: int = 8) -> list[dict]:
    """
    Manual lookup helper: searches across Google Books, Open Library, and Apple Books,
    returning candidates with their cover, title, author, year, pages, genre, and category!
    """
    q = query.strip()
    results = []
    seen_urls = set()

    # 1. Google Books
    try:
        gb_params = {"q": q, "maxResults": 6}
        if gb_api_key:
            gb_params["key"] = gb_api_key.strip()
        resp = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params=gb_params,
            headers=HEADERS,
            timeout=6,
        )
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
                            authors = vol.get("authors", [""])
                            cats = vol.get("categories", [])
                            c_genre, c_cat = classify_fiction_nonfiction("", cats)
                            yr = 2024
                            if vol.get("publishedDate"):
                                m = re.match(r"(\d{4})", str(vol["publishedDate"]))
                                if m:
                                    yr = int(m.group(1))
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

    # 2. Open Library
    try:
        resp = requests.get(
            "https://openlibrary.org/search.json",
            params={"q": q, "fields": "title,author_name,cover_i,number_of_pages_median,first_publish_year,subject", "limit": 6},
            headers=HEADERS,
            timeout=7,
        )
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
                            subs = doc.get("subject", [])
                            c_genre, c_cat = classify_fiction_nonfiction("", subs)
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

    # 3. Apple Books UK & US
    for country in ("GB", "US"):
        try:
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={"term": q, "country": country, "entity": "ebook", "limit": 4},
                headers=HEADERS,
                timeout=6,
            )
            if resp.status_code == 200:
                for item in resp.json().get("results", []):
                    art = item.get("artworkUrl100", "")
                    if art:
                        hd_url = re.sub(r"100x100bb", "800x800bb", art)
                        if hd_url not in seen_urls:
                            seen_urls.add(hd_url)
                            b_img = download_valid_image(hd_url)
                            if b_img:
                                c_genre, c_cat = classify_fiction_nonfiction(item.get("primaryGenreName", ""), item.get("genres", []))
                                rel_date = item.get("releaseDate", "")
                                yr = int(rel_date[:4]) if (len(rel_date) >= 4 and rel_date[:4].isdigit()) else 2024
                                results.append({
                                    "title": item.get("trackName", q),
                                    "author": item.get("artistName", ""),
                                    "source": f"Apple ({country})",
                                    "img_bytes": b_img,
                                    "pages": 320,
                                    "year": yr,
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
    palette = [
        (58, 79, 65), (122, 62, 52), (48, 72, 98),
        (104, 78, 54), (82, 58, 92), (44, 82, 84),
    ]
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


# --- SLIDE 2: AI-POWERED READING STATS & ANALYSIS GRAPHIC ---
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
    pad = max(40, int(margin * 0.85))
    content_w = canvas_w - 2 * pad

    card_bg = blend_rgb(bg_color, text_color, 0.06)
    card_border = blend_rgb(bg_color, text_color, 0.16)
    bar_track = blend_rgb(bg_color, text_color, 0.13)
    muted_text = blend_rgb(bg_color, text_color, 0.68)

    total_books = len(books)
    total_pages = sum(int(b.get("pages", 0)) for b in books)
    avg_pages = int(round(total_pages / total_books)) if total_books else 0

    fic_count = sum(1 for b in books if b.get("category") == "Fiction")
    nonfic_count = total_books - fic_count
    fic_pct = int(round((fic_count / total_books) * 100)) if total_books else 0
    nonfic_pct = 100 - fic_pct

    genre_counts = Counter(b.get("genre", "General") for b in books).most_common(4)

    f_title = get_font(int(46 * scale), bold=True)
    f_sec = get_font(int(22 * scale), bold=True)
    f_kpi_num = get_font(int(48 * scale), bold=True)
    f_kpi_lbl = get_font(int(18 * scale), bold=True)
    f_body = get_font(int(20 * scale), bold=False)
    f_body_b = get_font(int(20 * scale), bold=True)
    f_small = get_font(int(17 * scale), bold=True)

    y = pad

    stats_title = f"{header_text.strip()} • Reading Wrapped" if header_text.strip() else "My Reading Wrapped"
    bbox = draw.textbbox((0, 0), stats_title, font=f_title)
    draw.text(((canvas_w - (bbox[2] - bbox[0])) / 2, y), stats_title, fill=txt_rgb, font=f_title)
    y += (bbox[3] - bbox[1]) + int(24 * scale)

    footer_reserve = int(55 * scale) if footer_text.strip() else int(15 * scale)
    avail_h = canvas_h - y - pad - footer_reserve
    sec_gap = max(14, int(avail_h * 0.025))

    # 1. Top KPI Row (3 Boxes)
    kpi_h = max(100, int(avail_h * 0.15))
    kpi_gap = int(18 * scale)
    kpi_w = (content_w - 2 * kpi_gap) // 3
    kpis = [
        (f"{total_books:,}", "BOOKS READ"),
        (f"{total_pages:,}", "TOTAL PAGES"),
        (f"{avg_pages:,}", "AVG PAGES / BOOK"),
    ]
    for i, (val, label) in enumerate(kpis):
        kx = pad + i * (kpi_w + kpi_gap)
        draw.rounded_rectangle(
            (kx, y, kx + kpi_w, y + kpi_h),
            radius=int(16 * scale),
            fill=card_bg,
            outline=card_border,
            width=2,
        )
        vb = draw.textbbox((0, 0), val, font=f_kpi_num)
        vw = vb[2] - vb[0]
        draw.text((kx + (kpi_w - vw) / 2, y + int(kpi_h * 0.16)), val, fill=accent_rgb, font=f_kpi_num)

        lb = draw.textbbox((0, 0), label, font=f_kpi_lbl)
        lw = lb[2] - lb[0]
        draw.text((kx + (kpi_w - lw) / 2, y + int(kpi_h * 0.65)), label, fill=muted_text, font=f_kpi_lbl)

    y += kpi_h + sec_gap

    # 2. AI Literary Persona & Reading Critique Card (NEW!)
    ai_h = max(170, int(avail_h * 0.32))
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + ai_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    inner_x = pad + int(24 * scale)
    inner_w = content_w - 2 * int(24 * scale)

    persona_title = (
        ai_analysis.get("persona", "The Curious Polymath") if ai_analysis else "The Curious Polymath"
    )
    draw.text((inner_x, y + int(14 * scale)), "LITERARY PERSONA", fill=accent_rgb, font=f_small)

    f_persona = get_font(int(32 * scale), bold=True)
    draw.text((inner_x, y + int(36 * scale)), f"“{persona_title}”", fill=txt_rgb, font=f_persona)

    critique_text = (
        ai_analysis.get(
            "critique",
            "A balanced reader who navigates both narrative depth and conceptual insight across multiple disciplines.",
        )
        if ai_analysis
        else "A balanced reader who navigates both narrative depth and conceptual insight across multiple disciplines."
    )

    # Word-wrap critique into the card
    words = critique_text.split()
    lines, curr = [], ""
    for w in words:
        test = (curr + " " + w).strip()
        bb = draw.textbbox((0, 0), test, font=f_body)
        if (bb[2] - bb[0]) < inner_w - 10:
            curr = test
        else:
            lines.append(curr)
            curr = w
    if curr:
        lines.append(curr)

    cy = y + int(82 * scale)
    for ln in lines[:3]:
        draw.text((inner_x, cy), ln, fill=txt_rgb, font=f_body)
        cy += int(26 * scale)

    # Display unexpected book pairing if returned by AI
    if ai_analysis and ai_analysis.get("pairing"):
        pair_str = f"Standout Pairing: {ai_analysis['pairing']}"
        draw.text((inner_x, y + ai_h - int(34 * scale)), pair_str[:72] + ("…" if len(pair_str) > 72 else ""), fill=muted_text, font=f_small)

    y += ai_h + sec_gap

    # 3. Fiction vs Non-Fiction Proportion Card
    split_h = max(100, int(avail_h * 0.15))
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + split_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    draw.text((inner_x, y + int(12 * scale)), "FICTION VS. NON-FICTION", fill=txt_rgb, font=f_sec)

    bar_y = y + int(44 * scale)
    bar_h = max(18, int(22 * scale))
    draw.rounded_rectangle((inner_x, bar_y, inner_x + inner_w, bar_y + bar_h), radius=bar_h // 2, fill=bar_track)

    if fic_count > 0:
        fic_w = max(bar_h, int(inner_w * (fic_count / total_books)))
        draw.rounded_rectangle((inner_x, bar_y, inner_x + fic_w, bar_y + bar_h), radius=bar_h // 2, fill=accent_rgb)

    lbl_y = bar_y + bar_h + int(6 * scale)
    draw.text((inner_x, lbl_y), f"Fiction: {fic_count} ({fic_pct}%)", fill=txt_rgb, font=f_small)
    nb = draw.textbbox((0, 0), f"Non-Fiction: {nonfic_count} ({nonfic_pct}%)", font=f_small)
    draw.text((inner_x + inner_w - (nb[2] - nb[0]), lbl_y), f"Non-Fiction: {nonfic_count} ({nonfic_pct}%)", fill=muted_text, font=f_small)

    y += split_h + sec_gap

    # 4. Top Genres Breakdown
    rem_h = max(120, canvas_h - y - pad - footer_reserve)
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + rem_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    draw.text((inner_x, y + int(14 * scale)), "TOP GENRES", fill=txt_rgb, font=f_sec)

    g_start_y = y + int(48 * scale)
    max_g_count = genre_counts[0][1] if genre_counts else 1
    g_step = (rem_h - int(60 * scale)) / max(2, len(genre_counts))

    for idx, (g_name, g_count) in enumerate(genre_counts):
        gy = int(g_start_y + idx * g_step)
        g_pct = int(round((g_count / total_books) * 100))

        draw.text((inner_x, gy), f"{g_name}", fill=txt_rgb, font=f_body_b)
        cb = draw.textbbox((0, 0), f"{g_count} ({g_pct}%)", font=f_body_b)
        draw.text((inner_x + inner_w - (cb[2] - cb[0]), gy), f"{g_count} ({g_pct}%)", fill=accent_rgb, font=f_body_b)

        g_bar_y = gy + int(24 * scale)
        g_bar_h = max(7, int(9 * scale))
        draw.rounded_rectangle((inner_x, g_bar_y, inner_x + inner_w, g_bar_y + g_bar_h), radius=g_bar_h // 2, fill=bar_track)
        fill_w = max(g_bar_h, int(inner_w * (g_count / max_g_count)))
        draw.rounded_rectangle((inner_x, g_bar_y, inner_x + fill_w, g_bar_y + g_bar_h), radius=g_bar_h // 2, fill=accent_rgb)

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) / 2, canvas_h - pad - int(30 * scale)), footer_text, fill=txt_rgb, font=footer_font)

    return canvas


# --- SLIDE 3: PROCEDURAL 3D BOOKSHELF GENERATOR ---
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

        line_heights = []
        line_widths = []
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

    author_w = 0
    author_h = 0
    if clean_author:
        ab = t_draw.textbbox((0, 0), clean_author, font=f_author)
        author_w = ab[2] - ab[0]
        author_h = ab[3] - ab[1]

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


def render_realistic_spine(
    book: dict,
    spine_w: int,
    spine_h: int,
    scale: float,
    spine_style: str = "Wrapped Cover Art (Photorealistic)",
) -> Image.Image:
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
    for hx in range(5, spine_w - 5, 4):
        b_draw.line([(hx, crown_h - 2), (hx, crown_h + 1)], fill=(245, 235, 210, 220), width=1)

    if book.get("custom_spine_image") is not None:
        jacket_rgb = ImageOps.fit(
            book["custom_spine_image"].convert("RGB"),
            (spine_w, jacket_h),
            Image.Resampling.LANCZOS,
        )
        draw_typography = False
    elif spine_style == "Wrapped Cover Art (Photorealistic)":
        cov_wrapped = ImageOps.fit(book["image"].convert("RGB"), (spine_w, jacket_h), Image.Resampling.LANCZOS)
        cov_soft = cov_wrapped.filter(ImageFilter.GaussianBlur(1.4))
        solid_tint = Image.new("RGB", (spine_w, jacket_h), (r_base, g_base, b_base))
        jacket_rgb = Image.blend(cov_soft, solid_tint, 0.45)
        draw_typography = True
    else:
        cov_tex = ImageOps.fit(book["image"].convert("RGB"), (spine_w, jacket_h), Image.Resampling.BICUBIC)
        cov_tex = cov_tex.filter(ImageFilter.GaussianBlur(max(4, spine_w // 4)))
        solid_col = Image.new("RGB", (spine_w, jacket_h), (r_base, g_base, b_base))
        jacket_rgb = Image.blend(solid_col, cov_tex, 0.16)
        draw_typography = True

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

    if draw_typography:
        stat_sample = lit_jacket.resize((1, 1), Image.Resampling.BILINEAR).getpixel((0, 0))
        avg_lum = 0.299 * stat_sample[0] + 0.587 * stat_sample[1] + 0.114 * stat_sample[2]
        if avg_lum > 140:
            j_draw.rounded_rectangle(
                (4, int(jacket_h * 0.05), spine_w - 5, int(jacket_h * 0.95)),
                radius=4,
                fill=(255, 252, 245, 115),
            )
            primary_txt = (24, 20, 18, 252)
            secondary_txt = (55, 48, 42, 230)
        else:
            j_draw.rounded_rectangle(
                (4, int(jacket_h * 0.05), spine_w - 5, int(jacket_h * 0.95)),
                radius=4,
                fill=(12, 10, 10, 115),
            )
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

    j_draw.line([(0, 0), (0, jacket_h)], fill=(255, 255, 255, 45), width=1)
    j_draw.line([(spine_w - 1, 0), (spine_w - 1, jacket_h)], fill=(0, 0, 0, 165), width=1)

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
    spine_style: str,
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
    case_x = pad
    case_y = y_top
    case_w = canvas_w - 2 * pad
    case_h = canvas_h - case_y - pad - footer_reserve

    frame_thick = max(22, int(28 * scale))
    plank_thick = max(22, int(28 * scale))

    wall_shadow = Image.new("RGBA", (case_w + 48, case_h + 48), (0, 0, 0, 0))
    ws_draw = ImageDraw.Draw(wall_shadow)
    ws_draw.rounded_rectangle((24, 24, case_w + 24, case_h + 24), radius=int(16 * scale), fill=(0, 0, 0, 105))
    wall_shadow = wall_shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(wall_shadow, (case_x - 14, case_y - 10))

    frame_tex = create_wood_texture(case_w, case_h, theme["frame"], theme["grain_dark"], vertical=True)
    frame_rgba = add_rounded_corners(frame_tex, int(14 * scale))
    canvas.alpha_composite(frame_rgba, (case_x, case_y))

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

    p_draw = ImageDraw.Draw(plank_tex)
    p_draw.line([(0, ledge_depth), (inner_w, ledge_depth)], fill=(*theme["plank_edge"], 230), width=2)
    p_draw.rectangle((0, plank_total_h - 4, inner_w, plank_total_h), fill=(0, 0, 0, 95))

    n_shelves = max(1, min(shelf_rows, n_books))
    books_per_shelf = math.ceil(n_books / n_shelves)
    shelf_allowance_h = inner_h / n_shelves

    for s_idx in range(n_shelves):
        bay_top = int(inner_y + s_idx * shelf_allowance_h)
        bay_bottom = int(inner_y + (s_idx + 1) * shelf_allowance_h)
        plank_y = bay_bottom - plank_total_h
        book_rest_y = plank_y + ledge_depth
        clearance_h = book_rest_y - bay_top

        light_overlay = Image.new("RGBA", (inner_w, max(10, clearance_h)), (0, 0, 0, 0))
        lo_draw = ImageDraw.Draw(light_overlay)
        lo_draw.ellipse(
            (int(inner_w * 0.08), -int(clearance_h * 0.35), int(inner_w * 0.92), int(clearance_h * 0.85)),
            fill=(255, 244, 218, 26),
        )
        light_overlay = light_overlay.filter(ImageFilter.GaussianBlur(18))
        canvas.alpha_composite(light_overlay, (inner_x, bay_top))

        canvas.alpha_composite(plank_tex, (inner_x, plank_y))

        shelf_books = books[s_idx * books_per_shelf : (s_idx + 1) * books_per_shelf]
        if shelf_books:
            rel_widths = []
            for b in shelf_books:
                pages = max(140, min(850, int(b.get("pages", 320))))
                rel_w = 0.72 + 0.75 * ((pages - 140) / 710.0)
                rel_widths.append(rel_w)

            base_unit_w = min(int(inner_w * 0.13), int((inner_w * 0.88) / max(1.0, sum(rel_widths))))
            base_unit_w = max(30, base_unit_w)

            pixel_widths = [max(28, int(rw * base_unit_w)) for rw in rel_widths]
            total_row_w = sum(pixel_widths)
            if total_row_w > inner_w - 28:
                shrink = (inner_w - 28) / total_row_w
                pixel_widths = [max(22, int(pw * shrink)) for pw in pixel_widths]
                total_row_w = sum(pixel_widths)

            curr_x = inner_x + max(22, (inner_w - total_row_w) // 2)

            for book, spine_w in zip(shelf_books, pixel_widths):
                h_seed = int(hashlib.md5(book["title"].encode("utf-8")).hexdigest()[:4], 16)
                height_ratio = 0.81 + (h_seed % 13) * 0.01
                spine_h = max(65, int(clearance_h * height_ratio))

                pull_forward = h_seed % 4
                spine_y = book_rest_y - spine_h + pull_forward

                b_shadow = Image.new("RGBA", (spine_w + 22, spine_h + 14), (0, 0, 0, 0))
                bs_draw = ImageDraw.Draw(b_shadow)
                bs_draw.rounded_rectangle((8, 6, spine_w + 17, spine_h + 10), radius=5, fill=(0, 0, 0, 130))
                b_shadow = b_shadow.filter(ImageFilter.GaussianBlur(6))
                canvas.alpha_composite(b_shadow, (curr_x - 3, spine_y - 4))

                spine_img = render_realistic_spine(book, spine_w, spine_h, scale, spine_style=spine_style)
                canvas.alpha_composite(spine_img, (curr_x, spine_y))

                draw.line(
                    [(curr_x + 1, spine_y + spine_h), (curr_x + spine_w - 1, spine_y + spine_h)],
                    fill=(0, 0, 0, 185),
                    width=2,
                )
                curr_x += spine_w + 1

        overhang_h = max(20, int(34 * scale))
        ov_shadow = Image.new("RGBA", (inner_w, overhang_h), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(ov_shadow)
        for oy in range(overhang_h):
            alpha = int(135 * ((1.0 - oy / overhang_h) ** 1.7))
            ov_draw.line([(0, oy), (inner_w, oy)], fill=(0, 0, 0, alpha))
        canvas.alpha_composite(ov_shadow, (inner_x, bay_top))

    side_sh = Image.new("RGBA", (inner_w, inner_h), (0, 0, 0, 0))
    ss_draw = ImageDraw.Draw(side_sh)
    for sw in range(20):
        alpha = int(105 * (1 - sw / 20))
        ss_draw.line([(sw, 0), (sw, inner_h)], fill=(0, 0, 0, alpha))
        ss_draw.line([(inner_w - 1 - sw, 0), (inner_w - 1 - sw, inner_h)], fill=(0, 0, 0, alpha // 2))
    canvas.alpha_composite(side_sh, (inner_x, inner_y))

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) / 2, canvas_h - pad - int(32 * scale)), footer_text, fill=txt_rgb, font=footer_font)

    return canvas.convert("RGB")


def add_book_entry(meta: dict, custom_img: Image.Image | None = None):
    if custom_img is not None:
        img = custom_img.convert("RGB")
        found = True
    elif meta.get("img_bytes"):
        img = Image.open(io.BytesIO(meta["img_bytes"])).convert("RGB")
        found = True
    else:
        img = create_placeholder_cover(meta["title"], meta["author"])
        found = False

    spine_color = extract_dominant_color(img)

    st.session_state.books.append(
        {
            "id": st.session_state.next_id,
            "title": meta["title"],
            "author": meta["author"],
            "image": img,
            "custom_spine_image": None,
            "found": found,
            "genre": meta.get("genre", "General Fiction"),
            "category": meta.get("category", "Fiction"),
            "year": int(meta.get("year", 2024)),
            "pages": int(meta.get("pages", 320)),
            "spine_color": spine_color,
        }
    )
    st.session_state.next_id += 1
    st.session_state.ai_stats_cache = None
    st.session_state.ai_shelf_cache = None


# --- UI LAYOUT ---
st.title("📚 Social Media Book Collage, AI Stats & Bookshelf Maker")
st.markdown(
    "Enter the books you've read to generate **three matching social media graphics**: "
    "a **Cover Collage**, an **AI Reading Wrapped** page, and a **Photorealistic Bookshelf**."
)

col_left, col_right = st.columns([1.08, 1.22], gap="large")

with col_left:
    st.subheader("1. Add Your Books")

    tab_bulk, tab_single, tab_upload = st.tabs(
        ["📝 Paste Book List", "🔍 Add Single Book", "🖼 Add Manual Book"]
    )

    with tab_bulk:
        bulk_input = st.text_area(
            "Enter one book per line (Title & Author recommended):",
            placeholder=(
                "Head North by Andy Burnham\n"
                "Project Hail Mary by Andy Weir\n"
                "Tomorrow, and Tomorrow, and Tomorrow\n"
                "Dune by Frank Herbert"
            ),
            height=140,
        )
        if st.button("✨ Fetch Covers & Stats from List", type="primary", use_container_width=True):
            lines = [line.strip() for line in bulk_input.split("\n") if line.strip()]
            if lines:
                progress = st.progress(0, text="Resolving exact titles, ISBNs & covers...")
                for i, line in enumerate(lines):
                    meta = fetch_book_data(
                        line,
                        gemini_api_key=gemini_key,
                        groq_api_key=groq_key,
                        gb_api_key=google_books_key,
                    )
                    add_book_entry(meta)
                    progress.progress((i + 1) / len(lines), text=f"Loaded: {meta['title']}")
                progress.empty()
                st.rerun()

    with tab_single:
        single_query = st.text_input("Book Title / Author / ISBN", placeholder="e.g., Head North by Andy Burnham")
        if st.button("Add Book", use_container_width=True) and single_query.strip():
            with st.spinner("Searching exact book match..."):
                meta = fetch_book_data(
                    single_query.strip(),
                    gemini_api_key=gemini_key,
                    groq_api_key=groq_key,
                    gb_api_key=google_books_key,
                )
                add_book_entry(meta)
                st.rerun()

    with tab_upload:
        m_col1, m_col2 = st.columns(2)
        custom_title = m_col1.text_input("Book Title", placeholder="My Custom Book")
        custom_author = m_col2.text_input("Author", placeholder="Author Name")
        m_col3, m_col4, m_col5 = st.columns(3)
        custom_cat = m_col3.selectbox("Type", ["Fiction", "Non-Fiction"])
        custom_genre = m_col4.text_input("Genre", value="Literary Fiction")
        custom_pages = m_col5.number_input("Pages", min_value=1, max_value=5000, value=320)
        custom_year = st.number_input("Publication Year", min_value=1000, max_value=2030, value=2024)
        uploaded_file = st.file_uploader("Upload Cover Image (JPG/PNG/WebP)", type=["jpg", "jpeg", "png", "webp"])

        if st.button("Add Manual Book", use_container_width=True) and (custom_title or uploaded_file):
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

    # --- MANAGE BOOKS, UPLOAD COVERS & MANUAL LOOKUP (PULL COVER + STATS) ---
    if st.session_state.books:
        st.divider()
        header_col1, header_col2 = st.columns([3, 1])
        missing_count = sum(1 for b in st.session_state.books if not b.get("found", True))
        header_col1.markdown(f"**Current Books ({len(st.session_state.books)})**")
        if header_col2.button("🗑️ Clear All"):
            st.session_state.books = []
            st.session_state.cover_search_results = {}
            st.session_state.ai_stats_cache = None
            st.session_state.ai_shelf_cache = None
            st.rerun()

        if missing_count > 0:
            st.warning(
                f"⚠️ {missing_count} book(s) are using a generated cover. "
                "Open any book below to upload an image or click 'Find Covers & Stats'!"
            )

        for i, b in enumerate(st.session_state.books):
            book_id = b["id"]
            if "spine_color" not in b:
                b["spine_color"] = extract_dominant_color(b["image"])

            exp_label = f"📖 #{i + 1}: {b['title']}" + ("" if b.get("found", True) else " ⚠ (Needs Cover)")

            with st.expander(exp_label, expanded=not b.get("found", True)):
                top_c1, top_c2 = st.columns([1, 3.2])
                top_c1.image(b["image"], width=95, caption="Front Cover")
                if b.get("custom_spine_image") is not None:
                    top_c1.image(b["custom_spine_image"], width=45, caption="Custom Spine")

                with top_c2:
                    e_col1, e_col2 = st.columns(2)
                    b["title"] = e_col1.text_input("Title", value=b["title"], key=f"t_{book_id}")
                    b["author"] = e_col2.text_input("Author", value=b["author"], key=f"a_{book_id}")

                    up_col1, up_col2 = st.columns(2)
                    replacement_file = up_col1.file_uploader(
                        "📤 Upload Front Cover",
                        type=["jpg", "jpeg", "png", "webp"],
                        key=f"replace_cov_{book_id}",
                    )
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

                    spine_file = up_col2.file_uploader(
                        "📤 Upload Spine Photo (Optional)",
                        type=["jpg", "jpeg", "png", "webp"],
                        key=f"replace_sp_{book_id}",
                    )
                    if spine_file is not None:
                        sp_sig = f"sp_{spine_file.name}_{spine_file.size}"
                        if st.session_state.processed_uploads.get(f"sp_{book_id}") != sp_sig:
                            sp_img = Image.open(io.BytesIO(spine_file.getvalue())).convert("RGB")
                            b["custom_spine_image"] = sp_img
                            st.session_state.processed_uploads[f"sp_{book_id}"] = sp_sig
                            st.rerun()

                # --- MANUAL LOOKUP: PULL COVER AND ALL STATS ---
                st.markdown("**🔎 Manual Lookup — Search & Pick Cover + Metadata:**")
                lk_c1, lk_c2 = st.columns([3, 1.4])
                default_search = f"{b['title']} {b['author']}".strip()
                manual_q = lk_c1.text_input(
                    "Search query",
                    value=default_search,
                    key=f"mq_{book_id}",
                    label_visibility="collapsed",
                )
                if lk_c2.button("🔍 Find Covers & Stats", key=f"btn_mq_{book_id}", use_container_width=True):
                    with st.spinner("Searching Google Books, Open Library & Apple Books..."):
                        st.session_state.cover_search_results[book_id] = search_cover_candidates_with_stats(
                            manual_q, gb_api_key=google_books_key
                        )

                if book_id in st.session_state.cover_search_results:
                    cands = st.session_state.cover_search_results[book_id]
                    if not cands:
                        st.info("No matching editions found. Try searching by ISBN or a shorter title.")
                    else:
                        cand_cols = st.columns(min(3, len(cands)))
                        for c_idx, cand in enumerate(cands):
                            with cand_cols[c_idx % len(cand_cols)]:
                                st.image(cand["img_bytes"], width=90)
                                st.markdown(
                                    f"**{cand['title'][:24]}**  \n"
                                    f"<small>{cand['author']}  \n"
                                    f"{cand['genre']} • {cand['pages']}p ({cand['year']})</small>",
                                    unsafe_allow_html=True,
                                )
                                if st.button("Use Cover & Stats", key=f"pick_{book_id}_{c_idx}", use_container_width=True):
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
                                    del st.session_state.cover_search_results[book_id]
                                    st.session_state.ai_stats_cache = None
                                    st.rerun()

                st.divider()
                s_c1, s_c2, s_c3, s_c4, s_c5 = st.columns([1.3, 1.4, 0.9, 0.9, 0.8])
                b["category"] = s_c1.selectbox(
                    "Category",
                    ["Fiction", "Non-Fiction"],
                    index=0 if b.get("category") == "Fiction" else 1,
                    key=f"cat_{book_id}",
                )
                b["genre"] = s_c2.text_input("Genre", value=b.get("genre", "Fiction"), key=f"g_{book_id}")
                b["pages"] = s_c3.number_input(
                    "Pages", min_value=1, max_value=9999, value=int(b.get("pages", 320)), key=f"p_{book_id}"
                )
                b["year"] = s_c4.number_input(
                    "Year", min_value=1000, max_value=2035, value=int(b.get("year", 2024)), key=f"y_{book_id}"
                )
                b["spine_color"] = s_c5.color_picker(
                    "Spine", value=b.get("spine_color", "#4A6151"), key=f"sp_{book_id}"
                )

                act_c1, act_c2, act_c3 = st.columns([1, 1, 1.5])
                if act_c1.button("⬆️ Move Up", key=f"up_{book_id}", disabled=(i == 0)):
                    st.session_state.books[i - 1], st.session_state.books[i] = (
                        st.session_state.books[i],
                        st.session_state.books[i - 1],
                    )
                    st.rerun()
                if act_c2.button("🗑️ Remove", key=f"del_{book_id}"):
                    st.session_state.books.pop(i)
                    st.session_state.ai_stats_cache = None
                    st.rerun()
                if b.get("custom_spine_image") is not None:
                    if act_c3.button("Reset Spine Photo", key=f"rst_sp_{book_id}"):
                        b["custom_spine_image"] = None
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

    sh_col1, sh_col2, sh_col3 = st.columns([1.1, 1.4, 1])
    shelf_theme_name = sh_col1.selectbox("Bookcase Wood", list(SHELF_THEMES.keys()))
    shelf_render_mode = sh_col2.selectbox(
        "Bookshelf Generator",
        ["AI Studio Photograph (Gemini API)", "Procedural 3D Bookshelf (Instant)"],
    )
    shelf_rows = sh_col3.slider("Shelf Rows", min_value=1, max_value=6, value=default_shelves)

    t_col1, t_col2 = st.columns(2)
    header_text = t_col1.text_input("Header Title (Optional)", placeholder="e.g., 2026 Reading Wrap-Up")
    footer_text = t_col2.text_input("Footer Handle (Optional)", placeholder="e.g., @mybookgram")

    c_col1, c_col2, c_col3, c_col4 = st.columns(4)
    bg_color = c_col1.color_picker("Background", "#F5F2EB")
    text_color = c_col2.color_picker("Text Color", "#2C2623")
    accent_color = c_col3.color_picker("Stats Accent", "#C86D51")
    add_shadow = c_col4.checkbox("3D Shadow", value=True)

with col_right:
    st.subheader("3. Preview & Export All 3 Slides")

    if not st.session_state.books:
        st.info("👈 Add some books on the left to generate your Cover Collage, Reading Stats, and Bookshelf slides!")
    else:
        # Run AI Literary Analysis for Slide 2
        if st.session_state.ai_stats_cache is None and (gemini_key or groq_key):
            with st.spinner("🤖 AI is analyzing your reading list..."):
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

        # Slide 3: AI Generated vs Procedural Bookshelf
        if shelf_render_mode == "AI Studio Photograph (Gemini API)":
            if not gemini_key:
                st.warning("⚠️ Paste your free Gemini API key in the sidebar to generate AI studio photographs of your shelf!")
                shelf_img = generate_bookshelf_image(
                    books=st.session_state.books,
                    canvas_size=canvas_size,
                    margin=margin,
                    bg_color=bg_color,
                    text_color=text_color,
                    shelf_theme_name=shelf_theme_name,
                    shelf_rows=shelf_rows,
                    spine_style="Wrapped Cover Art (Photorealistic)",
                    header_text=header_text,
                    footer_text=footer_text,
                )
            else:
                if st.session_state.ai_shelf_cache is None:
                    with st.spinner("✨ Gemini is generating your photorealistic bookshelf photograph..."):
                        st.session_state.ai_shelf_cache = generate_ai_photorealistic_bookshelf(
                            st.session_state.books,
                            wood_style=shelf_theme_name,
                            gemini_api_key=gemini_key,
                            aspect_ratio=preset,
                        )
                shelf_img = st.session_state.ai_shelf_cache or generate_bookshelf_image(
                    books=st.session_state.books,
                    canvas_size=canvas_size,
                    margin=margin,
                    bg_color=bg_color,
                    text_color=text_color,
                    shelf_theme_name=shelf_theme_name,
                    shelf_rows=shelf_rows,
                    spine_style="Wrapped Cover Art (Photorealistic)",
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
                shelf_rows=shelf_rows,
                spine_style="Wrapped Cover Art (Photorealistic)",
                header_text=header_text,
                footer_text=footer_text,
            )

        # Convert to PNG bytes
        buf_collage = io.BytesIO()
        collage_img.save(buf_collage, format="PNG", quality=95)

        buf_stats = io.BytesIO()
        stats_img.save(buf_stats, format="PNG", quality=95)

        buf_shelf = io.BytesIO()
        shelf_img.save(buf_shelf, format="PNG", quality=95)

        dl_col1, dl_col2, dl_col3 = st.columns(3)
        dl_col1.download_button(
            label="📥 Slide 1: Collage",
            data=buf_collage.getvalue(),
            file_name="slide1_book_collage.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )
        dl_col2.download_button(
            label="📊 Slide 2: AI Stats",
            data=buf_stats.getvalue(),
            file_name="slide2_reading_stats.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )
        dl_col3.download_button(
            label="🪵 Slide 3: Bookshelf",
            data=buf_shelf.getvalue(),
            file_name="slide3_bookshelf.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )

        preview_tab1, preview_tab2, preview_tab3 = st.tabs(
            ["🖼️ Slide 1: Cover Collage", "📊 Slide 2: AI Stats Wrapped", "🪵 Slide 3: Bookshelf"]
        )
        with preview_tab1:
            st.image(
                collage_img,
                caption=f"Slide 1 — Cover Collage ({canvas_size[0]}x{canvas_size[1]} px)",
                use_container_width=True,
            )
        with preview_tab2:
            st.image(
                stats_img,
                caption=f"Slide 2 — AI Reading Wrapped ({canvas_size[0]}x{canvas_size[1]} px)",
                use_container_width=True,
            )
            if st.button("🔄 Re-analyze with AI", key="re_analyze"):
                st.session_state.ai_stats_cache = None
                st.rerun()

        with preview_tab3:
            st.image(
                shelf_img,
                caption=f"Slide 3 — Bookshelf ({canvas_size[0]}x{canvas_size[1]} px)",
                use_container_width=True,
            )
            if shelf_render_mode == "AI Studio Photograph (Gemini API)":
                if st.button("🔄 Regenerate AI Bookshelf Photo", key="re_shelf"):
                    st.session_state.ai_shelf_cache = None
                    st.rerun()
