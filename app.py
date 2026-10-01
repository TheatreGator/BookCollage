import hashlib
import io
import math
import random
import re
from collections import Counter
import requests
import streamlit as st
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Book Collage, Stats & Bookshelf Maker",
    page_icon="📚",
    layout="wide",
)

# --- SESSION STATE INITIALIZATION ---
if "books" not in st.session_state:
    st.session_state.books = []

if "next_id" not in st.session_state:
    st.session_state.next_id = 1

if "cover_search_results" not in st.session_state:
    # Maps book_id -> list of {"title", "author", "source", "img_bytes"}
    st.session_state.cover_search_results = {}

if "processed_uploads" not in st.session_state:
    st.session_state.processed_uploads = {}

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
        "frame": (126, 78, 38),
        "plank": (154, 98, 48),
        "plank_edge": (186, 126, 72),
        "back": (68, 42, 20),
        "grain_dark": (92, 54, 24),
    },
    "Dark Walnut": {
        "frame": (58, 36, 22),
        "plank": (76, 48, 30),
        "plank_edge": (102, 68, 44),
        "back": (32, 19, 11),
        "grain_dark": (38, 22, 12),
    },
    "Minimalist White": {
        "frame": (228, 225, 220),
        "plank": (242, 240, 236),
        "plank_edge": (252, 251, 249),
        "back": (192, 188, 180),
        "grain_dark": (210, 206, 198),
    },
    "Forest Sage": {
        "frame": (54, 74, 60),
        "plank": (70, 94, 78),
        "plank_edge": (92, 120, 100),
        "back": (34, 48, 38),
        "grain_dark": (42, 58, 46),
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


# --- FONT & COLOR HELPERS ---
def get_font(size: int, bold: bool = False):
    """Loads a clean TrueType font on Linux/Mac/Windows with fallback to PIL default."""
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=max(10, int(size)))
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=max(10, int(size)))
    except TypeError:
        return ImageFont.load_default()


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = hex_to_rgb(hex_color)
    return (r, g, b, alpha)


def blend_rgb(bg_hex: str, fg_hex: str, weight: float) -> tuple[int, int, int]:
    """Blends two hex colors into a solid RGB tuple so PIL never overwrites alpha channels."""
    r1, g1, b1 = hex_to_rgb(bg_hex)
    r2, g2, b2 = hex_to_rgb(fg_hex)
    w = max(0.0, min(1.0, weight))
    return (
        int(r1 * (1.0 - w) + r2 * w),
        int(g1 * (1.0 - w) + g2 * w),
        int(b1 * (1.0 - w) + b2 * w),
    )


def extract_dominant_color(pil_img: Image.Image) -> str:
    """Extracts a rich dominant hex color from a book cover for its spine."""
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


def get_contrast_text_color(hex_bg: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Returns (primary_text_rgba, secondary_text_rgba) based on spine luminance."""
    r, g, b = hex_to_rgb(hex_bg)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum > 155:
        return (30, 25, 22, 245), (70, 62, 55, 200)
    return (248, 242, 228, 245), (225, 212, 188, 200)


# --- QUERY PARSING & TITLE SIMILARITY SCORING ---
def parse_title_author(raw_query: str) -> tuple[str, str]:
    """Splits 'Title by Author' or 'Title - Author' into (title_part, author_part)."""
    q = raw_query.strip()
    by_match = re.split(r"\s+by\s+", q, maxsplit=1, flags=re.IGNORECASE)
    if len(by_match) == 2:
        return by_match[0].strip(), by_match[1].strip()

    dash_match = re.split(r"\s+[-–—]\s+", q, maxsplit=1)
    if len(dash_match) == 2:
        return dash_match[0].strip(), dash_match[1].strip()

    return q, ""


def normalize_tokens(text: str) -> list[str]:
    """Extracts lowercase alphanumeric words, ignoring trivial stopwords."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    stopwords = {"the", "a", "an", "of", "and", "in", "to", "for", "on", "with", "by"}
    filtered = [w for w in words if w not in stopwords]
    return filtered if filtered else words


def compute_match_score(req_title: str, req_author: str, cand_title: str, cand_author: str) -> float:
    """
    Scores how well a candidate book matches the user's requested title and author.
    Returns 0.0 if the title has practically no overlap (preventing wrong books by the same author).
    """
    if not cand_title:
        return 0.0

    # Strip subtitles from candidate for cleaner comparison
    cand_main_title = re.split(r"[:(\-–]", cand_title)[0].strip()

    req_t_tokens = set(normalize_tokens(req_title))
    cand_t_tokens = set(normalize_tokens(cand_title))
    cand_main_tokens = set(normalize_tokens(cand_main_title))

    if not req_t_tokens:
        return 0.0

    # Check token overlap with title
    overlap_full = len(req_t_tokens & cand_t_tokens) / len(req_t_tokens)
    overlap_main = len(req_t_tokens & cand_main_tokens) / max(1, len(req_t_tokens | cand_main_tokens))

    # Also check substring match for short titles like "Head North" or "Dune"
    req_clean = " ".join(normalize_tokens(req_title))
    cand_clean = " ".join(normalize_tokens(cand_title))
    exact_prefix = 1.0 if (req_clean and (cand_clean.startswith(req_clean) or req_clean in cand_clean)) else 0.0

    title_score = max(overlap_full * 0.75 + overlap_main * 0.25, exact_prefix * 0.9)

    # STRICT FILTER: If the title barely matches (< 0.45), reject immediately!
    if title_score < 0.45:
        return 0.0

    # Author bonus / penalty
    author_score = 0.5
    if req_author.strip():
        req_a_tokens = set(normalize_tokens(req_author))
        cand_a_tokens = set(normalize_tokens(cand_author))
        if req_a_tokens and cand_a_tokens:
            a_overlap = len(req_a_tokens & cand_a_tokens) / len(req_a_tokens)
            author_score = a_overlap
        elif not cand_a_tokens:
            author_score = 0.25

    return title_score * 0.72 + author_score * 0.28


def download_valid_image(url: str) -> bytes | None:
    """Downloads image bytes and verifies PIL can open it as a real cover."""
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
    """Determines (clean_genre, 'Fiction' or 'Non-Fiction') from API genre/subject tags."""
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
    if not clean_genre or clean_genre.lower() in {"books", "general", "ebook"}:
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


def fetch_book_data(raw_query: str) -> dict:
    """
    Searches UK & US Apple Books, Open Library, and Google Books with strict title+author verification
    so books like 'Head North by Andy Burnham' never match 'The Old Stones of Ireland'.
    """
    cache_key = f"book_meta_v4_{raw_query.strip().lower()}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    req_title, req_author = parse_title_author(raw_query)
    combined_search = f"{req_title} {req_author}".strip()

    candidates = []

    # 1. Search Apple Books (both UK 'GB' and US stores for regional releases)
    for country in ("GB", "US"):
        try:
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={"term": combined_search, "country": country, "media": "ebook", "entity": "ebook", "limit": 6},
                headers=HEADERS,
                timeout=7,
            )
            if resp.status_code == 200:
                for item in resp.json().get("results", []):
                    c_title = item.get("trackName", "")
                    c_author = item.get("artistName", "")
                    score = compute_match_score(req_title, req_author, c_title, c_author)
                    if score >= 0.45:
                        art_url = item.get("artworkUrl100", "")
                        hd_url = re.sub(r"100x100bb", "800x800bb", art_url) if art_url else ""
                        rel_date = item.get("releaseDate", "")
                        yr = int(rel_date[:4]) if (len(rel_date) >= 4 and rel_date[:4].isdigit()) else None
                        candidates.append({
                            "score": score + 0.05,  # Slight preference for HD Apple covers when tied
                            "title": c_title,
                            "author": c_author,
                            "cover_url": hd_url,
                            "primary_genre": item.get("primaryGenreName", ""),
                            "subjects": item.get("genres", []),
                            "year": yr,
                            "pages": None,
                        })
        except Exception:
            pass

    # 2. Search Open Library (structured title/author search + general search)
    try:
        ol_params = {
            "q": combined_search,
            "fields": "title,author_name,cover_i,first_publish_year,number_of_pages_median,subject",
            "limit": 6,
        }
        resp = requests.get("https://openlibrary.org/search.json", params=ol_params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            for doc in resp.json().get("docs", []):
                c_title = doc.get("title", "")
                c_authors = doc.get("author_name", [""])
                c_author = ", ".join(c_authors[:2]) if c_authors else ""
                score = compute_match_score(req_title, req_author, c_title, c_author)
                if score >= 0.45:
                    cov_id = doc.get("cover_i")
                    cov_url = f"https://covers.openlibrary.org/b/id/{cov_id}-L.jpg" if cov_id else ""
                    candidates.append({
                        "score": score,
                        "title": c_title,
                        "author": c_authors[0] if c_authors else "",
                        "cover_url": cov_url,
                        "primary_genre": "",
                        "subjects": doc.get("subject", [])[:12],
                        "year": int(doc["first_publish_year"]) if doc.get("first_publish_year") else None,
                        "pages": int(doc["number_of_pages_median"]) if doc.get("number_of_pages_median") else None,
                    })
    except Exception:
        pass

    # 3. Search Google Books (using intitle/inauthor when available)
    try:
        gb_q = f'intitle:"{req_title}"' + (f' inauthor:"{req_author}"' if req_author else "")
        resp = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": gb_q, "maxResults": 5},
            headers=HEADERS,
            timeout=7,
        )
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                vol = item.get("volumeInfo", {})
                c_title = vol.get("title", "")
                c_authors = vol.get("authors", [""])
                c_author = ", ".join(c_authors)
                score = compute_match_score(req_title, req_author, c_title, c_author)
                if score >= 0.45:
                    links = vol.get("imageLinks", {})
                    thumb = links.get("thumbnail") or links.get("smallThumbnail") or ""
                    high_res = thumb.replace("http://", "https://").replace("&edge=curl", "")
                    yr = None
                    if vol.get("publishedDate"):
                        m = re.match(r"(\d{4})", str(vol["publishedDate"]))
                        if m:
                            yr = int(m.group(1))
                    candidates.append({
                        "score": score,
                        "title": c_title,
                        "author": c_authors[0] if c_authors else "",
                        "cover_url": high_res,
                        "primary_genre": "",
                        "subjects": vol.get("categories", []),
                        "year": yr,
                        "pages": int(vol["pageCount"]) if vol.get("pageCount") else None,
                    })
    except Exception:
        pass

    # Sort all verified candidates by match score descending
    candidates.sort(key=lambda x: x["score"], reverse=True)

    best_title = req_title.title() if req_title.islower() else req_title
    best_author = req_author.title() if req_author.islower() else req_author
    img_bytes = None
    primary_genre = ""
    subjects = []
    year = None
    pages = None

    if candidates:
        best_title = candidates[0]["title"]
        best_author = candidates[0]["author"] or best_author

    # Aggregate best cover, page count, year, and subjects across valid matching editions
    for cand in candidates:
        if img_bytes is None and cand["cover_url"]:
            img_bytes = download_valid_image(cand["cover_url"])
        if not pages and cand["pages"]:
            pages = cand["pages"]
        if not year and cand["year"]:
            year = cand["year"]
        if not primary_genre and cand["primary_genre"]:
            primary_genre = cand["primary_genre"]
        if cand["subjects"]:
            subjects.extend(cand["subjects"])

    clean_genre, category = classify_fiction_nonfiction(primary_genre, subjects)

    data = {
        "title": best_title,
        "author": best_author,
        "img_bytes": img_bytes,
        "genre": clean_genre,
        "category": category,
        "year": year if year else 2024,
        "pages": pages if pages else 320,
    }
    if img_bytes is not None:
        st.session_state[cache_key] = data
    return data


def search_cover_candidates(query: str, max_results: int = 6) -> list[dict]:
    """
    Manual lookup helper: returns up to `max_results` visual cover options
    across Apple Books (UK/US), Open Library, and Google Books for the user to pick from.
    """
    q = query.strip()
    results = []
    seen_urls = set()

    # 1. Apple Books UK & US
    for country in ("GB", "US"):
        try:
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={"term": q, "country": country, "media": "ebook", "entity": "ebook", "limit": 5},
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
                                results.append({
                                    "title": item.get("trackName", q),
                                    "author": item.get("artistName", ""),
                                    "source": f"Apple Books ({country})",
                                    "img_bytes": b_img,
                                })
                                if len(results) >= max_results:
                                    return results
        except Exception:
            pass

    # 2. Open Library
    try:
        resp = requests.get(
            "https://openlibrary.org/search.json",
            params={"q": q, "fields": "title,author_name,cover_i", "limit": 6},
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
                            results.append({
                                "title": doc.get("title", q),
                                "author": authors[0] if authors else "",
                                "source": "Open Library",
                                "img_bytes": b_img,
                            })
                            if len(results) >= max_results:
                                return results
    except Exception:
        pass

    # 3. Google Books
    try:
        resp = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": q, "maxResults": 5},
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
                            results.append({
                                "title": vol.get("title", q),
                                "author": authors[0] if authors else "",
                                "source": "Google Books",
                                "img_bytes": b_img,
                            })
                            if len(results) >= max_results:
                                return results
    except Exception:
        pass

    return results


def create_placeholder_cover(title: str, author: str = "") -> Image.Image:
    """Generates a clean fallback cover if an online cover cannot be found."""
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
    """Applies rounded corners to a PIL Image."""
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
    """Renders the book covers onto a social-media-sized canvas."""
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
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - margin - 40),
            footer_text,
            fill=txt_rgb,
            font=footer_font,
        )

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


# --- SLIDE 2: READING STATS GRAPHIC GENERATOR (FIXED SOLID RGB BLENDING) ---
def generate_stats_image(
    books: list,
    canvas_size: tuple[int, int],
    margin: int,
    bg_color: str,
    text_color: str,
    accent_color: str,
    header_text: str,
    footer_text: str,
) -> Image.Image:
    """Renders a high-contrast social media Reading Stats ('Wrapped') infographic."""
    canvas_w, canvas_h = canvas_size
    bg_rgb = hex_to_rgb(bg_color)
    txt_rgb = hex_to_rgb(text_color)
    accent_rgb = hex_to_rgb(accent_color)

    # Use an RGB canvas with pre-blended solid RGB colors so PIL never clobbers alpha channels
    canvas = Image.new("RGB", (canvas_w, canvas_h), bg_rgb)
    draw = ImageDraw.Draw(canvas)

    if not books:
        return canvas

    scale = min(canvas_w / 1080.0, canvas_h / 1080.0)
    pad = max(40, int(margin * 0.85))
    content_w = canvas_w - 2 * pad

    # Solid pre-blended colors guarantee visible text on any background
    card_bg = blend_rgb(bg_color, text_color, 0.06)
    card_border = blend_rgb(bg_color, text_color, 0.16)
    bar_track = blend_rgb(bg_color, text_color, 0.13)
    secondary_bar = blend_rgb(bg_color, accent_color, 0.62)
    muted_text = blend_rgb(bg_color, text_color, 0.68)

    total_books = len(books)
    total_pages = sum(int(b.get("pages", 0)) for b in books)
    avg_pages = int(round(total_pages / total_books)) if total_books else 0

    fic_count = sum(1 for b in books if b.get("category") == "Fiction")
    nonfic_count = total_books - fic_count
    fic_pct = int(round((fic_count / total_books) * 100)) if total_books else 0
    nonfic_pct = 100 - fic_pct

    genre_counts = Counter(b.get("genre", "General") for b in books).most_common(5)

    decades = Counter(f"{(int(b.get('year', 2020)) // 10) * 10}s" for b in books)
    top_decades = sorted(decades.items(), key=lambda x: x[0], reverse=True)[:4]

    longest_book = max(books, key=lambda b: int(b.get("pages", 0)))
    shortest_book = min(books, key=lambda b: int(b.get("pages", 0)))
    oldest_book = min(books, key=lambda b: int(b.get("year", 2024)))
    newest_book = max(books, key=lambda b: int(b.get("year", 2024)))

    f_title = get_font(int(46 * scale), bold=True)
    f_sec = get_font(int(23 * scale), bold=True)
    f_kpi_num = get_font(int(50 * scale), bold=True)
    f_kpi_lbl = get_font(int(19 * scale), bold=True)
    f_body_b = get_font(int(21 * scale), bold=True)
    f_body = get_font(int(20 * scale), bold=False)
    f_small = get_font(int(18 * scale), bold=True)

    y = pad

    stats_title = f"{header_text.strip()} • Reading Stats" if header_text.strip() else "My Reading Stats"
    bbox = draw.textbbox((0, 0), stats_title, font=f_title)
    draw.text(((canvas_w - (bbox[2] - bbox[0])) / 2, y), stats_title, fill=txt_rgb, font=f_title)
    y += (bbox[3] - bbox[1]) + int(28 * scale)

    footer_reserve = int(55 * scale) if footer_text.strip() else int(15 * scale)
    avail_h = canvas_h - y - pad - footer_reserve
    sec_gap = max(14, int(avail_h * 0.03))

    # 1. Top KPI Cards
    kpi_h = max(105, int(avail_h * 0.16))
    kpi_gap = int(20 * scale)
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
            radius=int(18 * scale),
            fill=card_bg,
            outline=card_border,
            width=2,
        )
        vb = draw.textbbox((0, 0), val, font=f_kpi_num)
        vw = vb[2] - vb[0]
        draw.text((kx + (kpi_w - vw) / 2, y + int(kpi_h * 0.16)), val, fill=accent_rgb, font=f_kpi_num)

        lb = draw.textbbox((0, 0), label, font=f_kpi_lbl)
        lw = lb[2] - lb[0]
        draw.text((kx + (kpi_w - lw) / 2, y + int(kpi_h * 0.66)), label, fill=muted_text, font=f_kpi_lbl)

    y += kpi_h + sec_gap

    # 2. Fiction vs Non-Fiction Card
    split_h = max(110, int(avail_h * 0.16))
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + split_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    inner_x = pad + int(26 * scale)
    inner_w = content_w - 2 * int(26 * scale)

    draw.text((inner_x, y + int(14 * scale)), "FICTION VS. NON-FICTION", fill=txt_rgb, font=f_sec)

    bar_y = y + int(48 * scale)
    bar_h = max(20, int(24 * scale))
    draw.rounded_rectangle((inner_x, bar_y, inner_x + inner_w, bar_y + bar_h), radius=bar_h // 2, fill=bar_track)

    if fic_count > 0:
        fic_w = max(bar_h, int(inner_w * (fic_count / total_books)))
        draw.rounded_rectangle((inner_x, bar_y, inner_x + fic_w, bar_y + bar_h), radius=bar_h // 2, fill=accent_rgb)

    lbl_y = bar_y + bar_h + int(8 * scale)
    fic_label = f"Fiction: {fic_count} ({fic_pct}%)"
    nonfic_label = f"Non-Fiction: {nonfic_count} ({nonfic_pct}%)"
    draw.text((inner_x, lbl_y), fic_label, fill=txt_rgb, font=f_small)
    nb = draw.textbbox((0, 0), nonfic_label, font=f_small)
    draw.text((inner_x + inner_w - (nb[2] - nb[0]), lbl_y), nonfic_label, fill=muted_text, font=f_small)

    y += split_h + sec_gap

    # 3. Top Genres Card
    genre_h = max(185, int(avail_h * 0.34))
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + genre_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    draw.text((inner_x, y + int(16 * scale)), "TOP GENRES", fill=txt_rgb, font=f_sec)

    g_start_y = y + int(52 * scale)
    n_genres = max(1, len(genre_counts))
    row_step = (genre_h - int(64 * scale)) / max(3, n_genres)
    max_g_count = genre_counts[0][1] if genre_counts else 1

    for idx, (g_name, g_count) in enumerate(genre_counts):
        gy = int(g_start_y + idx * row_step)
        g_pct = int(round((g_count / total_books) * 100))

        label_str = f"{g_name}"
        count_str = f"{g_count} book{'s' if g_count > 1 else ''} ({g_pct}%)"
        draw.text((inner_x, gy), label_str, fill=txt_rgb, font=f_body_b)
        cb = draw.textbbox((0, 0), count_str, font=f_body_b)
        draw.text((inner_x + inner_w - (cb[2] - cb[0]), gy), count_str, fill=accent_rgb, font=f_body_b)

        g_bar_y = gy + int(26 * scale)
        g_bar_h = max(8, int(11 * scale))
        draw.rounded_rectangle(
            (inner_x, g_bar_y, inner_x + inner_w, g_bar_y + g_bar_h),
            radius=g_bar_h // 2,
            fill=bar_track,
        )
        fill_w = max(g_bar_h, int(inner_w * (g_count / max_g_count)))
        draw.rounded_rectangle(
            (inner_x, g_bar_y, inner_x + fill_w, g_bar_y + g_bar_h),
            radius=g_bar_h // 2,
            fill=accent_rgb if idx == 0 else secondary_bar,
        )

    y += genre_h + sec_gap

    # 4. Bottom Row: Publication Eras & Book Highlights
    rem_h = max(125, canvas_h - y - pad - footer_reserve)
    half_w = (content_w - kpi_gap) // 2

    draw.rounded_rectangle(
        (pad, y, pad + half_w, y + rem_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    lx = pad + int(22 * scale)
    draw.text((lx, y + int(16 * scale)), "PUBLICATION ERAS", fill=txt_rgb, font=f_sec)

    ey = y + int(50 * scale)
    for dec_label, dec_count in top_decades:
        dec_str = f"{dec_label}: {dec_count} book{'s' if dec_count > 1 else ''}"
        draw.text((lx, ey), f"•  {dec_str}", fill=txt_rgb, font=f_body)
        ey += int(28 * scale)

    span_str = f"Range: {oldest_book.get('year')} – {newest_book.get('year')}"
    draw.text((lx, y + rem_h - int(32 * scale)), span_str, fill=muted_text, font=f_small)

    rx = pad + half_w + kpi_gap
    draw.rounded_rectangle(
        (rx, y, rx + half_w, y + rem_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    rix = rx + int(22 * scale)
    draw.text((rix, y + int(16 * scale)), "HIGHLIGHTS", fill=txt_rgb, font=f_sec)

    def short_title(t: str, limit: int = 23) -> str:
        return t if len(t) <= limit else t[: limit - 1] + "…"

    hy = y + int(50 * scale)
    draw.text((rix, hy), "LONGEST READ", fill=muted_text, font=f_small)
    hy += int(22 * scale)
    draw.text(
        (rix, hy),
        f"{short_title(longest_book['title'])} ({longest_book.get('pages', 0)}p)",
        fill=txt_rgb,
        font=f_body_b,
    )

    hy += int(34 * scale)
    draw.text((rix, hy), "SHORTEST READ", fill=muted_text, font=f_small)
    hy += int(22 * scale)
    draw.text(
        (rix, hy),
        f"{short_title(shortest_book['title'])} ({shortest_book.get('pages', 0)}p)",
        fill=txt_rgb,
        font=f_body_b,
    )

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - pad - int(30 * scale)),
            footer_text,
            fill=txt_rgb,
            font=footer_font,
        )

    return canvas


# --- SLIDE 3: PHOTOREALISTIC BOOKSHELF GENERATOR ---
def create_wood_texture(width: int, height: int, base_rgb: tuple, dark_rgb: tuple, vertical: bool = False) -> Image.Image:
    """Generates a realistic procedural wood-grain texture with fibers and subtle sheen."""
    # Generate low-res noise and stretch along the grain axis
    rng = random.Random(42)
    gw = 24 if vertical else max(60, width // 6)
    gh = max(60, height // 6) if vertical else 24

    noise_img = Image.new("RGB", (gw, gh))
    pixels = []
    for _ in range(gw * gh):
        t = rng.random() ** 1.4
        r = int(base_rgb[0] * (1 - t * 0.35) + dark_rgb[0] * (t * 0.35))
        g = int(base_rgb[1] * (1 - t * 0.35) + dark_rgb[1] * (t * 0.35))
        b = int(base_rgb[2] * (1 - t * 0.35) + dark_rgb[2] * (t * 0.35))
        pixels.append((r, g, b))
    noise_img.putdata(pixels)

    stretched = noise_img.resize((width, height), Image.Resampling.BICUBIC)
    return stretched.filter(ImageFilter.GaussianBlur(0.8))


def render_realistic_spine(book: dict, spine_w: int, spine_h: int, scale: float) -> Image.Image:
    """
    Renders a photorealistic 3D hardcover book spine with:
    - Subtle cloth/cover texture blend
    - Cylindrical 3D lighting gradient + French-joint hinge grooves
    - Stitched headbands, raised spine hubs (on thicker books), and embossed foil lettering
    """
    spine_hex = book.get("spine_color") or extract_dominant_color(book["image"])
    r_base, g_base, b_base = hex_to_rgb(spine_hex)
    primary_txt, secondary_txt = get_contrast_text_color(spine_hex)

    spine_img = Image.new("RGBA", (spine_w, spine_h), (0, 0, 0, 0))

    # 1. Base cloth/cover-textured body
    cov_tex = ImageOps.fit(book["image"].convert("RGB"), (spine_w, spine_h), Image.Resampling.BICUBIC)
    cov_tex = cov_tex.filter(ImageFilter.GaussianBlur(max(3, spine_w // 5)))
    solid_col = Image.new("RGB", (spine_w, spine_h), (r_base, g_base, b_base))
    # Blend 18% of blurred cover art variations into the solid spine color for organic depth
    body_rgb = Image.blend(solid_col, cov_tex, 0.18)

    # 2. Horizontal 3D cylindrical lighting profile across spine width (1 x spine_w stretched)
    lighting_strip = Image.new("L", (spine_w, 1))
    hinge_l = max(3, int(spine_w * 0.09))
    hinge_r = max(3, int(spine_w * 0.91))
    l_vals = []
    for x in range(spine_w):
        nx = x / max(1, spine_w - 1)
        if x in (hinge_l, hinge_r):
            # French-joint hinge groove indentation
            val = 95
        elif x == hinge_l + 1:
            # Ridge highlight right next to left groove
            val = 165
        else:
            # Smooth cylindrical roll-off: lit on left-center, shadowed toward right edge
            curve = math.sin(nx * math.pi)
            specular = math.exp(-((nx - 0.26) ** 2) / 0.035) * 38
            right_shade = (nx ** 1.8) * 55
            val = int(max(65, min(195, 120 + curve * 22 + specular - right_shade)))
        l_vals.append(val)
    lighting_strip.putdata(l_vals)
    lighting_map = lighting_strip.resize((spine_w, spine_h), Image.Resampling.BILINEAR)

    # Apply cylindrical lighting to body_rgb using hard-light style scaling
    lit_pixels = ImageChops.multiply(body_rgb, lighting_map.convert("RGB"))
    lit_pixels = ImageEnhance.Brightness(lit_pixels).enhance(1.42)

    # Mask spine with slightly rounded crown at top
    mask = Image.new("L", (spine_w, spine_h), 0)
    m_draw = ImageDraw.Draw(mask)
    top_rad = max(3, min(9, spine_w // 7))
    m_draw.rounded_rectangle((0, 0, spine_w - 1, spine_h + top_rad), radius=top_rad, fill=255)
    spine_img.paste(lit_pixels.convert("RGBA"), (0, 0), mask)

    s_draw = ImageDraw.Draw(spine_img)

    # 3. Stitched cloth headband at top edge & tailband at bottom
    hb_h = max(3, int(4 * scale))
    s_draw.rectangle((3, 1, spine_w - 4, 1 + hb_h), fill=(235, 225, 205, 190))
    for hx in range(4, spine_w - 4, 4):
        s_draw.line([(hx, 1), (hx, 1 + hb_h)], fill=(160, 50, 40, 180), width=1)

    # 4. Raised horizontal spine cords / hubs and foil bands
    band_y_top = int(spine_h * 0.065)
    band_y_bot = int(spine_h * 0.915)

    # Raised hub shadow + highlight
    for by in (band_y_top, band_y_bot):
        s_draw.line([(2, by - 2), (spine_w - 3, by - 2)], fill=(255, 255, 255, 70), width=1)
        s_draw.line([(2, by), (spine_w - 3, by)], fill=secondary_txt, width=2)
        s_draw.line([(2, by + 2), (spine_w - 3, by + 2)], fill=(0, 0, 0, 110), width=2)
        s_draw.line([(2, by + 6), (spine_w - 3, by + 6)], fill=secondary_txt, width=1)

    # 5. Miniature framed cover vignette or colophon near bottom of wider spines
    text_max_len = band_y_bot - band_y_top - 24
    if spine_w >= 44:
        thumb_w = spine_w - 16
        thumb_h = int(thumb_w * 1.35)
        if thumb_h < int(spine_h * 0.22):
            ty_pos = band_y_bot - thumb_h - 12
            # Gold/foil frame around mini cover
            s_draw.rounded_rectangle(
                (6, ty_pos - 2, 6 + thumb_w + 3, ty_pos + thumb_h + 2),
                radius=4,
                fill=(0, 0, 0, 90),
                outline=secondary_txt,
                width=1,
            )
            mini_cov = ImageOps.fit(
                book["image"].convert("RGBA"),
                (thumb_w, thumb_h),
                Image.Resampling.LANCZOS,
            )
            mini_cov = add_rounded_corners(mini_cov, 3)
            spine_img.alpha_composite(mini_cov, (8, ty_pos))
            text_max_len = ty_pos - band_y_top - 22

    # 6. Embossed Vertical Typography (with subtle 1px debossed shadow)
    font_sz = max(12, min(int(spine_w * 0.40), int(25 * scale)))
    f_spine_title = get_font(font_sz, bold=True)
    f_spine_author = get_font(max(10, int(font_sz * 0.76)), bold=False)

    clean_title = re.split(r"[:(]", book["title"].strip())[0].strip() or book["title"].strip()
    author_last = book["author"].strip().split()[-1] if book.get("author", "").strip() else ""

    while len(clean_title) > 4:
        tb = s_draw.textbbox((0, 0), clean_title, font=f_spine_title)
        ab = s_draw.textbbox((0, 0), f"   {author_last}", font=f_spine_author) if author_last else (0, 0, 0, 0)
        if (tb[2] - tb[0]) + (ab[2] - ab[0]) <= text_max_len - 8:
            break
        clean_title = clean_title[:-2].rstrip() + "…"

    txt_layer = Image.new("RGBA", (max(12, text_max_len), spine_w), (0, 0, 0, 0))
    t_draw = ImageDraw.Draw(txt_layer)

    tb = t_draw.textbbox((0, 0), clean_title, font=f_spine_title)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    ty = (spine_w - th) // 2 - 2

    # Stamped shadow + foil text
    t_draw.text((7, ty + 1), clean_title, fill=(0, 0, 0, 120), font=f_spine_title)
    t_draw.text((6, ty), clean_title, fill=primary_txt, font=f_spine_title)

    if author_last:
        sep_x = 6 + tw + 12
        ab = t_draw.textbbox((0, 0), author_last, font=f_spine_author)
        aw, ah = ab[2] - ab[0], ab[3] - ab[1]
        if sep_x + aw < text_max_len - 4:
            ay = (spine_w - ah) // 2 - 1
            t_draw.text((sep_x + 1, ay + 1), author_last, fill=(0, 0, 0, 100), font=f_spine_author)
            t_draw.text((sep_x, ay), author_last, fill=secondary_txt, font=f_spine_author)

    rotated_txt = txt_layer.rotate(270, expand=True)
    spine_img.alpha_composite(rotated_txt, (0, band_y_top + 14))

    # Crisp outer book edges
    s_draw.line([(0, top_rad), (0, spine_h)], fill=(0, 0, 0, 115), width=1)
    s_draw.line([(spine_w - 1, top_rad), (spine_w - 1, spine_h)], fill=(0, 0, 0, 155), width=1)

    return spine_img


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
    """Renders a photorealistic wooden bookcase populated with 3D textured book spines."""
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

    frame_thick = max(20, int(28 * scale))
    plank_thick = max(20, int(26 * scale))

    # Soft wall drop shadow behind the bookcase
    wall_shadow = Image.new("RGBA", (case_w + 40, case_h + 40), (0, 0, 0, 0))
    ws_draw = ImageDraw.Draw(wall_shadow)
    ws_draw.rounded_rectangle((20, 20, case_w + 20, case_h + 20), radius=int(16 * scale), fill=(0, 0, 0, 95))
    wall_shadow = wall_shadow.filter(ImageFilter.GaussianBlur(12))
    canvas.alpha_composite(wall_shadow, (case_x - 12, case_y - 8))

    # Wood-textured outer frame
    frame_tex = create_wood_texture(case_w, case_h, theme["frame"], theme["grain_dark"], vertical=True)
    frame_rgba = add_rounded_corners(frame_tex, int(14 * scale))
    canvas.alpha_composite(frame_rgba, (case_x, case_y))

    # Recessed dark wood backing panel
    inner_x = case_x + frame_thick
    inner_y = case_y + frame_thick
    inner_w = case_w - 2 * frame_thick
    inner_h = case_h - 2 * frame_thick

    back_tex = create_wood_texture(inner_w, inner_h, theme["back"], theme["grain_dark"], vertical=True)
    canvas.alpha_composite(back_tex.convert("RGBA"), (inner_x, inner_y))

    # Inner frame side shadows for 3D depth
    side_sh = Image.new("RGBA", (inner_w, inner_h), (0, 0, 0, 0))
    ss_draw = ImageDraw.Draw(side_sh)
    for sw in range(18):
        alpha = int(95 * (1 - sw / 18))
        ss_draw.line([(sw, 0), (sw, inner_h)], fill=(0, 0, 0, alpha))
        ss_draw.line([(inner_w - 1 - sw, 0), (inner_w - 1 - sw, inner_h)], fill=(0, 0, 0, alpha // 2))
    canvas.alpha_composite(side_sh, (inner_x, inner_y))

    # Pre-generate horizontal wood plank texture
    plank_tex = create_wood_texture(inner_w, plank_thick, theme["plank"], theme["grain_dark"], vertical=False).convert("RGBA")
    p_draw = ImageDraw.Draw(plank_tex)
    # Top bevel highlight & bottom lip shadow on each plank
    p_draw.rectangle((0, 0, inner_w, max(3, int(4 * scale))), fill=(*theme["plank_edge"], 220))
    p_draw.line([(0, 0), (inner_w, 0)], fill=(255, 255, 255, 90), width=1)
    p_draw.rectangle((0, plank_thick - 4, inner_w, plank_thick), fill=(0, 0, 0, 85))

    n_shelves = max(1, min(shelf_rows, n_books))
    books_per_shelf = math.ceil(n_books / n_shelves)
    shelf_allowance_h = inner_h / n_shelves

    for s_idx in range(n_shelves):
        bay_top = int(inner_y + s_idx * shelf_allowance_h)
        bay_bottom = int(inner_y + (s_idx + 1) * shelf_allowance_h)
        plank_top = bay_bottom - plank_thick
        clearance_h = plank_top - bay_top

        # Soft gradient shadow cast downward from the shelf above
        overhang_h = max(18, int(32 * scale))
        ov_shadow = Image.new("RGBA", (inner_w, overhang_h), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(ov_shadow)
        for oy in range(overhang_h):
            alpha = int(125 * ((1.0 - oy / overhang_h) ** 1.6))
            ov_draw.line([(0, oy), (inner_w, oy)], fill=(0, 0, 0, alpha))
        canvas.alpha_composite(ov_shadow, (inner_x, bay_top))

        shelf_books = books[s_idx * books_per_shelf : (s_idx + 1) * books_per_shelf]
        if shelf_books:
            rel_widths = []
            for b in shelf_books:
                pages = max(140, min(850, int(b.get("pages", 320))))
                rel_w = 0.68 + 0.78 * ((pages - 140) / 710.0)
                rel_widths.append(rel_w)

            base_unit_w = min(
                int(inner_w * 0.125),
                int((inner_w * 0.88) / max(1.0, sum(rel_widths))),
            )
            base_unit_w = max(28, base_unit_w)

            pixel_widths = [max(26, int(rw * base_unit_w)) for rw in rel_widths]
            total_row_w = sum(pixel_widths)
            if total_row_w > inner_w - 28:
                shrink = (inner_w - 28) / total_row_w
                pixel_widths = [max(20, int(pw * shrink)) for pw in pixel_widths]
                total_row_w = sum(pixel_widths)

            curr_x = inner_x + max(22, (inner_w - total_row_w) // 2)

            for book, spine_w in zip(shelf_books, pixel_widths):
                h_seed = int(hashlib.md5(book["title"].encode("utf-8")).hexdigest()[:4], 16)
                height_ratio = 0.80 + (h_seed % 14) * 0.01
                spine_h = max(60, int(clearance_h * height_ratio))
                spine_y = plank_top - spine_h

                # Deep cast shadow behind & to the right of the book against the back wall
                b_shadow = Image.new("RGBA", (spine_w + 18, spine_h + 10), (0, 0, 0, 0))
                bs_draw = ImageDraw.Draw(b_shadow)
                bs_draw.rounded_rectangle((6, 6, spine_w + 14, spine_h + 10), radius=5, fill=(0, 0, 0, 115))
                b_shadow = b_shadow.filter(ImageFilter.GaussianBlur(5))
                canvas.alpha_composite(b_shadow, (curr_x - 2, spine_y - 2))

                # Render the 3D textured hardcover spine
                spine_img = render_realistic_spine(book, spine_w, spine_h, scale)
                canvas.alpha_composite(spine_img, (curr_x, spine_y))

                # Grounding contact shadow at the bottom edge where book meets wood
                draw.line([(curr_x, plank_top - 1), (curr_x + spine_w, plank_top - 1)], fill=(0, 0, 0, 160), width=2)

                curr_x += spine_w + 1

        # Composite wooden shelf plank across bay bottom
        canvas.alpha_composite(plank_tex, (inner_x, plank_top))

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - pad - int(32 * scale)),
            footer_text,
            fill=txt_rgb,
            font=footer_font,
        )

    return canvas.convert("RGB")


def add_book_entry(meta: dict, custom_img: Image.Image | None = None):
    """Adds a standardized book dictionary to session state."""
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
            "found": found,
            "genre": meta.get("genre", "General Fiction"),
            "category": meta.get("category", "Fiction"),
            "year": int(meta.get("year", 2024)),
            "pages": int(meta.get("pages", 320)),
            "spine_color": spine_color,
        }
    )
    st.session_state.next_id += 1


# --- UI LAYOUT ---
st.title("📚 Social Media Book Collage, Stats & Bookshelf Maker")
st.markdown(
    "Enter the books you've read to generate **three matching social media graphics**: "
    "a **Cover Collage**, a **Reading Stats ('Wrapped')** page, and a **Photorealistic Bookshelf**."
)

col_left, col_right = st.columns([1.08, 1.22], gap="large")

with col_left:
    st.subheader("1. Add Your Books")

    tab_bulk, tab_single, tab_upload = st.tabs(
        ["📝 Paste Book List", "🔍 Add Single Book", "🖼️ Add Manual Book"]
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
                progress = st.progress(0, text="Fetching covers, spine colors & metadata...")
                for i, line in enumerate(lines):
                    meta = fetch_book_data(line)
                    add_book_entry(meta)
                    progress.progress((i + 1) / len(lines), text=f"Loaded: {meta['title']}")
                progress.empty()
                st.rerun()

    with tab_single:
        single_query = st.text_input("Book Title / Author / ISBN", placeholder="e.g., Head North by Andy Burnham")
        if st.button("Add Book", use_container_width=True) and single_query.strip():
            with st.spinner("Searching cover and book stats..."):
                meta = fetch_book_data(single_query.strip())
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

    # --- MANAGE BOOKS, UPLOAD COVERS & MANUAL LOOKUP ---
    if st.session_state.books:
        st.divider()
        header_col1, header_col2 = st.columns([3, 1])
        missing_count = sum(1 for b in st.session_state.books if not b.get("found", True))
        header_col1.markdown(f"**Current Books ({len(st.session_state.books)})**")
        if header_col2.button("🗑️ Clear All"):
            st.session_state.books = []
            st.session_state.cover_search_results = {}
            st.rerun()

        if missing_count > 0:
            st.warning(
                f"⚠️ {missing_count} book(s) are using a placeholder cover. "
                "Open any book below to upload an image, paste an image URL, or run a manual cover lookup!"
            )

        for i, b in enumerate(st.session_state.books):
            book_id = b["id"]
            if "spine_color" not in b:
                b["spine_color"] = extract_dominant_color(b["image"])

            # Keep expander label stable so widgets inside never reset during file upload
            exp_label = f"📖 #{i + 1}: {b['title']}" + ("" if b.get("found", True) else " ⚠️ (Needs Cover)")

            with st.expander(exp_label, expanded=not b.get("found", True)):
                top_c1, top_c2 = st.columns([1, 3.2])
                top_c1.image(b["image"], width=95)

                with top_c2:
                    e_col1, e_col2 = st.columns(2)
                    b["title"] = e_col1.text_input("Title", value=b["title"], key=f"t_{book_id}")
                    b["author"] = e_col2.text_input("Author", value=b["author"], key=f"a_{book_id}")

                    # Option A: Upload local image file (tracked by signature so it never loops)
                    replacement_file = st.file_uploader(
                        "📤 Upload Cover File (JPG/PNG/WebP)",
                        type=["jpg", "jpeg", "png", "webp"],
                        key=f"replace_cov_{book_id}",
                    )
                    if replacement_file is not None:
                        file_sig = f"{replacement_file.name}_{replacement_file.size}"
                        if st.session_state.processed_uploads.get(book_id) != file_sig:
                            new_img = Image.open(io.BytesIO(replacement_file.getvalue())).convert("RGB")
                            b["image"] = new_img
                            b["spine_color"] = extract_dominant_color(new_img)
                            b["found"] = True
                            st.session_state.processed_uploads[book_id] = file_sig
                            st.rerun()

                    # Option B: Paste direct Image URL
                    url_c1, url_c2 = st.columns([3, 1.2])
                    img_url_in = url_c1.text_input(
                        "Or paste Cover Image URL",
                        placeholder="https://...",
                        key=f"url_{book_id}",
                        label_visibility="collapsed",
                    )
                    if url_c2.button("🔗 Load URL", key=f"btn_url_{book_id}", use_container_width=True) and img_url_in.strip():
                        img_bytes = download_valid_image(img_url_in.strip())
                        if img_bytes:
                            new_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                            b["image"] = new_img
                            b["spine_color"] = extract_dominant_color(new_img)
                            b["found"] = True
                            st.rerun()
                        else:
                            st.error("Could not load a valid image from that URL.")

                # Option C: Interactive Manual Cover Lookup & Visual Picker
                st.markdown("**🔎 Manual Cover Lookup (Search by Title, Author, or ISBN):**")
                lk_c1, lk_c2 = st.columns([3, 1.2])
                default_search = f"{b['title']} {b['author']}".strip()
                manual_q = lk_c1.text_input(
                    "Search query",
                    value=default_search,
                    key=f"mq_{book_id}",
                    label_visibility="collapsed",
                )
                if lk_c2.button("🔍 Find Covers", key=f"btn_mq_{book_id}", use_container_width=True):
                    with st.spinner("Searching Apple Books UK/US, Open Library & Google Books..."):
                        st.session_state.cover_search_results[book_id] = search_cover_candidates(manual_q)

                if book_id in st.session_state.cover_search_results:
                    cands = st.session_state.cover_search_results[book_id]
                    if not cands:
                        st.info("No covers found for that query. Try searching the ISBN or shorter title.")
                    else:
                        cand_cols = st.columns(min(3, len(cands)))
                        for c_idx, cand in enumerate(cands):
                            with cand_cols[c_idx % len(cand_cols)]:
                                st.image(cand["img_bytes"], width=80)
                                st.caption(f"{cand['title'][:22]} ({cand['source']})")
                                if st.button("Use Cover", key=f"pick_{book_id}_{c_idx}", use_container_width=True):
                                    picked_img = Image.open(io.BytesIO(cand["img_bytes"])).convert("RGB")
                                    b["image"] = picked_img
                                    b["spine_color"] = extract_dominant_color(picked_img)
                                    b["found"] = True
                                    del st.session_state.cover_search_results[book_id]
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

                act_c1, act_c2, _ = st.columns([1, 1, 2])
                if act_c1.button("⬆️ Move Up", key=f"up_{book_id}", disabled=(i == 0)):
                    st.session_state.books[i - 1], st.session_state.books[i] = (
                        st.session_state.books[i],
                        st.session_state.books[i - 1],
                    )
                    st.rerun()
                if act_c2.button("🗑️ Remove", key=f"del_{book_id}"):
                    st.session_state.books.pop(i)
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
    shelf_theme_name = sh_col1.selectbox("Bookcase Wood Style", list(SHELF_THEMES.keys()))
    shelf_rows = sh_col2.slider("Number of Bookcase Shelves", min_value=1, max_value=6, value=default_shelves)

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
        )

        shelf_img = generate_bookshelf_image(
            books=st.session_state.books,
            canvas_size=canvas_size,
            margin=margin,
            bg_color=bg_color,
            text_color=text_color,
            shelf_theme_name=shelf_theme_name,
            shelf_rows=shelf_rows,
            header_text=header_text,
            footer_text=footer_text,
        )

        # Convert all three images to PNG bytes
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
            label="📊 Slide 2: Stats",
            data=buf_stats.getvalue(),
            file_name="slide2_reading_stats.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )
        dl_col3.download_button(
            label="🪵 Slide 3: Bookshelf",
            data=buf_shelf.getvalue(),
            file_name="slide3_bookshelf_spines.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )

        preview_tab1, preview_tab2, preview_tab3 = st.tabs(
            ["🖼️ Slide 1: Cover Collage", "📊 Slide 2: Reading Stats", "🪵 Slide 3: Bookshelf Spines"]
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
                caption=f"Slide 2 — Reading Stats ({canvas_size[0]}x{canvas_size[1]} px)",
                use_container_width=True,
            )
        with preview_tab3:
            st.image(
                shelf_img,
                caption=f"Slide 3 — Bookshelf Spines ({canvas_size[0]}x{canvas_size[1]} px)",
                use_container_width=True,
            )
