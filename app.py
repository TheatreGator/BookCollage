import hashlib
import io
import math
import re
from collections import Counter
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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

NONFICTION_KEYWORDS = {
    "nonfiction", "non-fiction", "biography", "biographies", "memoir", "memoirs",
    "history", "historical", "science", "psychology", "business", "economics",
    "self-help", "self-improvement", "philosophy", "politics", "health", "mind",
    "body", "cooking", "travel", "true crime", "essays", "reference", "education",
    "computers", "technology", "religion", "spirituality", "art", "music", "nature"
}

FICTION_HINTS = {
    "fiction", "novel", "fantasy", "sci-fi", "science fiction", "romance",
    "thriller", "mystery", "mysteries", "horror", "historical fiction",
    "literary", "classics", "young adult", "ya", "dystopian", "adventure"
}

SHELF_THEMES = {
    "Warm Oak": {
        "frame": "#8B5A2B",
        "plank": "#A66E38",
        "plank_edge": "#C48B52",
        "back": "#523418",
    },
    "Dark Walnut": {
        "frame": "#3B2618",
        "plank": "#4E3321",
        "plank_edge": "#69462F",
        "back": "#24160D",
    },
    "Minimalist White": {
        "frame": "#E6E4E0",
        "plank": "#F5F4F0",
        "plank_edge": "#FFFFFF",
        "back": "#CFCBC4",
    },
    "Forest Sage": {
        "frame": "#384B3E",
        "plank": "#4A6151",
        "plank_edge": "#607A68",
        "back": "#26352B",
    },
}


# --- FONT HELPER ---
def get_font(size: int, bold: bool = False):
    """Loads a clean TrueType font on Linux/Mac/Windows with fallback to PIL default."""
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# --- HELPER FUNCTIONS ---
def clean_search_query(raw_query: str) -> str:
    """Removes 'by', dashes, and extra noise that break book search APIs."""
    q = raw_query.strip()
    q = re.sub(r"\s+by\s+", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+[-–—]\s+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def extract_dominant_color(pil_img: Image.Image) -> str:
    """Extracts an attractive dominant hex color from a book cover for its spine."""
    try:
        small = pil_img.convert("RGB").resize((40, 40), Image.Resampling.BILINEAR)
        # Quantize into 6 representative colors
        quantized = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT).convert("RGB")
        counts = Counter(list(quantized.getdata()))

        best_rgb = (68, 92, 78)
        best_score = -1.0
        for (r, g, b), count in counts.items():
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            # Avoid pure white or pure black backgrounds if a richer color exists
            if 25 < lum < 235:
                saturation = (max(r, g, b) - min(r, g, b)) / 255.0
                score = count * (1.0 + saturation * 1.2)
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
    h = hex_bg.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum > 150:
        return (32, 28, 25, 245), (65, 58, 52, 190)
    return (250, 246, 238, 245), (225, 216, 200, 190)


def classify_fiction_nonfiction(genre_str: str, subjects: list[str]) -> tuple[str, str]:
    """Determines (clean_genre, 'Fiction' or 'Non-Fiction') from API genre/subject tags."""
    combined = " ".join([genre_str] + subjects[:8]).lower()

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
    }
    clean_genre = genre_map.get(clean_genre, clean_genre)
    return clean_genre, category


def create_placeholder_cover(title: str, author: str = "") -> Image.Image:
    """Generates a clean fallback cover if an online cover cannot be found."""
    width, height = 400, 600
    # Deterministic rich color per book title
    digest = hashlib.md5(title.encode("utf-8")).hexdigest()
    palette = [
        (58, 79, 65), (122, 62, 52), (48, 72, 98),
        (104, 78, 54), (82, 58, 92), (44, 82, 84)
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


def download_valid_image(url: str, headers: dict) -> bytes | None:
    """Downloads image bytes and verifies PIL can open it."""
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200 and len(resp.content) > 1500:
            img = Image.open(io.BytesIO(resp.content))
            if img.width > 50 and img.height > 50:
                return resp.content
    except Exception:
        pass
    return None


def fetch_book_data(raw_query: str) -> dict:
    """
    Fetches cover image AND metadata (title, author, genre, category, year, pages)
    by combining Apple Books, Open Library, and Google Books.
    """
    cache_key = f"book_meta_v3_{raw_query.strip().lower()}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    cleaned_query = clean_search_query(raw_query)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    title = raw_query.strip()
    author = ""
    img_bytes = None
    primary_genre = ""
    subjects = []
    year = None
    pages = None

    # 1. Apple Books API
    try:
        itunes_url = "https://itunes.apple.com/search"
        params = {"term": cleaned_query, "media": "ebook", "entity": "ebook", "limit": 4}
        resp = requests.get(itunes_url, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for item in results:
                art_url = item.get("artworkUrl100")
                if art_url:
                    hd_url = re.sub(r"100x100bb", "800x800bb", art_url)
                    candidate_bytes = download_valid_image(hd_url, headers)
                    if candidate_bytes:
                        img_bytes = candidate_bytes
                        title = item.get("trackName", title)
                        author = item.get("artistName", author)
                        primary_genre = item.get("primaryGenreName", "")
                        subjects.extend(item.get("genres", []))
                        rel_date = item.get("releaseDate", "")
                        if len(rel_date) >= 4 and rel_date[:4].isdigit():
                            year = int(rel_date[:4])
                        break
    except Exception:
        pass

    # 2. Open Library API
    try:
        ol_url = "https://openlibrary.org/search.json"
        params = {
            "q": cleaned_query,
            "fields": "title,author_name,cover_i,first_publish_year,number_of_pages_median,subject",
            "limit": 4,
        }
        resp = requests.get(ol_url, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            docs = resp.json().get("docs", [])
            for doc in docs:
                if not pages and doc.get("number_of_pages_median"):
                    pages = int(doc["number_of_pages_median"])
                if doc.get("first_publish_year"):
                    year = int(doc["first_publish_year"])
                if doc.get("subject"):
                    subjects.extend(doc["subject"][:10])
                if not author and doc.get("author_name"):
                    author = doc["author_name"][0]
                if title == raw_query.strip() and doc.get("title"):
                    title = doc["title"]

                if img_bytes is None and doc.get("cover_i"):
                    img_url = f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg"
                    candidate_bytes = download_valid_image(img_url, headers)
                    if candidate_bytes:
                        img_bytes = candidate_bytes
                if pages and img_bytes:
                    break
    except Exception:
        pass

    # 3. Fallback to Google Books
    if img_bytes is None or pages is None:
        try:
            gb_url = "https://www.googleapis.com/books/v1/volumes"
            resp = requests.get(gb_url, params={"q": cleaned_query, "maxResults": 3}, headers=headers, timeout=6)
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    vol = item.get("volumeInfo", {})
                    if not pages and vol.get("pageCount"):
                        pages = int(vol["pageCount"])
                    if not year and vol.get("publishedDate"):
                        m = re.match(r"(\d{4})", str(vol["publishedDate"]))
                        if m:
                            year = int(m.group(1))
                    if vol.get("categories"):
                        subjects.extend(vol["categories"])
                    if img_bytes is None:
                        links = vol.get("imageLinks", {})
                        thumb = links.get("thumbnail") or links.get("smallThumbnail")
                        if thumb:
                            high_res = thumb.replace("http://", "https://").replace("&edge=curl", "")
                            candidate_bytes = download_valid_image(high_res, headers)
                            if candidate_bytes:
                                img_bytes = candidate_bytes
                                title = vol.get("title", title)
                                if not author and vol.get("authors"):
                                    author = vol["authors"][0]
        except Exception:
            pass

    clean_genre, category = classify_fiction_nonfiction(primary_genre, subjects)

    data = {
        "title": title,
        "author": author,
        "img_bytes": img_bytes,
        "genre": clean_genre,
        "category": category,
        "year": year if year else 2024,
        "pages": pages if pages else 320,
    }
    if img_bytes is not None:
        st.session_state[cache_key] = data
    return data


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


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Converts a hex color string to an RGBA tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


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
    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg_color)
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

    if header_text.strip():
        header_font = get_font(52, bold=True)
        bbox = draw.textbbox((0, 0), header_text, font=header_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) / 2, margin + 10), header_text, fill=text_color, font=header_font)

    if footer_text.strip():
        footer_font = get_font(28, bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - margin - 40),
            footer_text,
            fill=text_color,
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


# --- SLIDE 2: READING STATS GRAPHIC GENERATOR ---
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
    """Renders a matching social media Reading Stats ('Wrapped') infographic."""
    canvas_w, canvas_h = canvas_size
    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg_color)
    draw = ImageDraw.Draw(canvas)

    if not books:
        return canvas.convert("RGB")

    scale = min(canvas_w / 1080.0, canvas_h / 1080.0)
    pad = max(40, int(margin * 0.85))
    content_w = canvas_w - 2 * pad

    card_bg = hex_to_rgba(text_color, 18)
    card_border = hex_to_rgba(text_color, 38)
    bar_track = hex_to_rgba(text_color, 28)
    accent_rgba = hex_to_rgba(accent_color, 255)
    secondary_rgba = hex_to_rgba(accent_color, 145)
    muted_text = hex_to_rgba(text_color, 175)

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
    f_sec = get_font(int(24 * scale), bold=True)
    f_kpi_num = get_font(int(50 * scale), bold=True)
    f_kpi_lbl = get_font(int(20 * scale), bold=False)
    f_body_b = get_font(int(22 * scale), bold=True)
    f_body = get_font(int(21 * scale), bold=False)
    f_small = get_font(int(18 * scale), bold=False)

    y = pad

    stats_title = f"{header_text.strip()} • Reading Stats" if header_text.strip() else "My Reading Stats"
    bbox = draw.textbbox((0, 0), stats_title, font=f_title)
    draw.text(((canvas_w - (bbox[2] - bbox[0])) / 2, y), stats_title, fill=text_color, font=f_title)
    y += (bbox[3] - bbox[1]) + int(28 * scale)

    footer_reserve = int(55 * scale) if footer_text.strip() else int(15 * scale)
    avail_h = canvas_h - y - pad - footer_reserve
    sec_gap = max(14, int(avail_h * 0.03))

    # KPI Cards
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
        draw.text((kx + (kpi_w - vw) / 2, y + kpi_h * 0.18), val, fill=accent_rgba, font=f_kpi_num)

        lb = draw.textbbox((0, 0), label, font=f_kpi_lbl)
        lw = lb[2] - lb[0]
        draw.text((kx + (kpi_w - lw) / 2, y + kpi_h * 0.66), label, fill=muted_text, font=f_kpi_lbl)

    y += kpi_h + sec_gap

    # Fiction vs Non-Fiction Card
    split_h = max(105, int(avail_h * 0.15))
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + split_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    inner_x = pad + int(26 * scale)
    inner_w = content_w - 2 * int(26 * scale)

    draw.text((inner_x, y + int(14 * scale)), "FICTION VS. NON-FICTION", fill=text_color, font=f_sec)

    bar_y = y + int(50 * scale)
    bar_h = max(22, int(26 * scale))
    draw.rounded_rectangle((inner_x, bar_y, inner_x + inner_w, bar_y + bar_h), radius=bar_h // 2, fill=bar_track)

    if fic_count > 0:
        fic_w = max(bar_h, int(inner_w * (fic_count / total_books)))
        draw.rounded_rectangle((inner_x, bar_y, inner_x + fic_w, bar_y + bar_h), radius=bar_h // 2, fill=accent_rgba)

    lbl_y = bar_y + bar_h + int(8 * scale)
    fic_label = f"● Fiction: {fic_count} ({fic_pct}%)"
    nonfic_label = f"Non-Fiction: {nonfic_count} ({nonfic_pct}%) ●"
    draw.text((inner_x, lbl_y), fic_label, fill=text_color, font=f_small)
    nb = draw.textbbox((0, 0), nonfic_label, font=f_small)
    draw.text((inner_x + inner_w - (nb[2] - nb[0]), lbl_y), nonfic_label, fill=muted_text, font=f_small)

    y += split_h + sec_gap

    # Top Genres Card
    genre_h = max(180, int(avail_h * 0.34))
    draw.rounded_rectangle(
        (pad, y, pad + content_w, y + genre_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    draw.text((inner_x, y + int(16 * scale)), "TOP GENRES", fill=text_color, font=f_sec)

    g_start_y = y + int(54 * scale)
    n_genres = max(1, len(genre_counts))
    row_step = (genre_h - int(66 * scale)) / max(3, n_genres)
    max_g_count = genre_counts[0][1] if genre_counts else 1

    for idx, (g_name, g_count) in enumerate(genre_counts):
        gy = int(g_start_y + idx * row_step)
        g_pct = int(round((g_count / total_books) * 100))

        label_str = f"{g_name}"
        count_str = f"{g_count} ({g_pct}%)"
        draw.text((inner_x, gy), label_str, fill=text_color, font=f_body)
        cb = draw.textbbox((0, 0), count_str, font=f_body_b)
        draw.text((inner_x + inner_w - (cb[2] - cb[0]), gy), count_str, fill=text_color, font=f_body_b)

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
            fill=accent_rgba if idx == 0 else secondary_rgba,
        )

    y += genre_h + sec_gap

    # Bottom Row: Publication Eras & Highlights
    rem_h = max(120, canvas_h - y - pad - footer_reserve)
    half_w = (content_w - kpi_gap) // 2

    draw.rounded_rectangle(
        (pad, y, pad + half_w, y + rem_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    lx = pad + int(22 * scale)
    draw.text((lx, y + int(16 * scale)), "PUBLICATION ERAS", fill=text_color, font=f_sec)

    ey = y + int(52 * scale)
    for dec_label, dec_count in top_decades:
        dec_str = f"{dec_label}: {dec_count} book{'s' if dec_count > 1 else ''}"
        draw.text((lx, ey), f"▸  {dec_str}", fill=text_color, font=f_body)
        ey += int(30 * scale)

    span_str = f"Span: {oldest_book.get('year')} – {newest_book.get('year')}"
    draw.text((lx, y + rem_h - int(34 * scale)), span_str, fill=muted_text, font=f_small)

    rx = pad + half_w + kpi_gap
    draw.rounded_rectangle(
        (rx, y, rx + half_w, y + rem_h),
        radius=int(18 * scale),
        fill=card_bg,
        outline=card_border,
        width=2,
    )
    rix = rx + int(22 * scale)
    draw.text((rix, y + int(16 * scale)), "HIGHLIGHTS", fill=text_color, font=f_sec)

    def short_title(t: str, limit: int = 24) -> str:
        return t if len(t) <= limit else t[: limit - 1] + "…"

    hy = y + int(52 * scale)
    draw.text((rix, hy), "LONGEST READ", fill=muted_text, font=f_small)
    hy += int(22 * scale)
    draw.text(
        (rix, hy),
        f"{short_title(longest_book['title'])} ({longest_book.get('pages', 0)}p)",
        fill=text_color,
        font=f_body_b,
    )

    hy += int(36 * scale)
    draw.text((rix, hy), "SHORTEST READ", fill=muted_text, font=f_small)
    hy += int(22 * scale)
    draw.text(
        (rix, hy),
        f"{short_title(shortest_book['title'])} ({shortest_book.get('pages', 0)}p)",
        fill=text_color,
        font=f_body_b,
    )

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - pad - int(30 * scale)),
            footer_text,
            fill=text_color,
            font=footer_font,
        )

    return canvas.convert("RGB")


# --- SLIDE 3: BOOKSHELF SPINES GENERATOR ---
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
    """Renders the user's books as vertical hardcover spines standing on a wooden bookcase."""
    canvas_w, canvas_h = canvas_size
    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg_color)
    draw = ImageDraw.Draw(canvas)

    n_books = len(books)
    if n_books == 0:
        return canvas.convert("RGB")

    theme = SHELF_THEMES.get(shelf_theme_name, SHELF_THEMES["Warm Oak"])
    frame_col = hex_to_rgba(theme["frame"])
    plank_col = hex_to_rgba(theme["plank"])
    edge_col = hex_to_rgba(theme["plank_edge"])
    back_col = hex_to_rgba(theme["back"])

    scale = min(canvas_w / 1080.0, canvas_h / 1080.0)
    pad = max(36, int(margin * 0.85))

    y_top = pad
    if header_text.strip():
        f_title = get_font(int(48 * scale), bold=True)
        bbox = draw.textbbox((0, 0), header_text, font=f_title)
        draw.text(((canvas_w - (bbox[2] - bbox[0])) / 2, y_top), header_text, fill=text_color, font=f_title)
        y_top += (bbox[3] - bbox[1]) + int(28 * scale)

    footer_reserve = int(60 * scale) if footer_text.strip() else int(10 * scale)
    case_x = pad
    case_y = y_top
    case_w = canvas_w - 2 * pad
    case_h = canvas_h - case_y - pad - footer_reserve

    # Outer bookcase frame with subtle drop shadow
    frame_thick = max(18, int(26 * scale))
    plank_thick = max(18, int(24 * scale))

    draw.rounded_rectangle(
        (case_x + 8, case_y + 10, case_x + case_w + 8, case_y + case_h + 10),
        radius=int(16 * scale),
        fill=(0, 0, 0, 70),
    )
    draw.rounded_rectangle(
        (case_x, case_y, case_x + case_w, case_y + case_h),
        radius=int(16 * scale),
        fill=frame_col,
    )

    # Recessed interior backing
    inner_x = case_x + frame_thick
    inner_y = case_y + frame_thick
    inner_w = case_w - 2 * frame_thick
    inner_h = case_h - 2 * frame_thick
    draw.rectangle((inner_x, inner_y, inner_x + inner_w, inner_y + inner_h), fill=back_col)

    # Split books across shelves
    n_shelves = max(1, min(shelf_rows, n_books))
    books_per_shelf = math.ceil(n_books / n_shelves)
    shelf_Allowance_h = inner_h / n_shelves

    for s_idx in range(n_shelves):
        bay_top = int(inner_y + s_idx * shelf_Allowance_h)
        bay_bottom = int(inner_y + (s_idx + 1) * shelf_Allowance_h)
        plank_top = bay_bottom - plank_thick
        clearance_h = plank_top - bay_top

        # Top interior shadow under previous shelf
        draw.rectangle(
            (inner_x, bay_top, inner_x + inner_w, bay_top + max(8, int(14 * scale))),
            fill=(0, 0, 0, 65),
        )

        # Books on this shelf
        shelf_books = books[s_idx * books_per_shelf : (s_idx + 1) * books_per_shelf]
        if shelf_books:
            # Calculate relative spine widths from page counts (clamped between 140 and 850 pages)
            rel_widths = []
            for b in shelf_books:
                pages = max(140, min(850, int(b.get("pages", 320))))
                rel_w = 0.68 + 0.75 * ((pages - 140) / 710.0)
                rel_widths.append(rel_w)

            # Determine pixel widths so books fit comfortably on the shelf
            base_unit_w = min(
                int(inner_w * 0.13),
                int((inner_w * 0.88) / max(1.0, sum(rel_widths))),
            )
            base_unit_w = max(28, base_unit_w)

            pixel_widths = [max(26, int(rw * base_unit_w)) for rw in rel_widths]
            total_row_w = sum(pixel_widths)
            if total_row_w > inner_w - 24:
                shrink = (inner_w - 24) / total_row_w
                pixel_widths = [max(20, int(pw * shrink)) for pw in pixel_widths]
                total_row_w = sum(pixel_widths)

            # Start left-aligned with a cozy shelf margin (or centered if lots of books)
            curr_x = inner_x + max(20, (inner_w - total_row_w) // 2)

            for b_idx, (book, spine_w) in enumerate(zip(shelf_books, pixel_widths)):
                # Deterministic height variation (82% to 94% of shelf clearance)
                h_seed = int(hashlib.md5(book["title"].encode("utf-8")).hexdigest()[:4], 16)
                height_ratio = 0.82 + (h_seed % 13) * 0.01
                spine_h = max(60, int(clearance_h * height_ratio))
                spine_y = plank_top - spine_h

                spine_hex = book.get("spine_color") or extract_dominant_color(book["image"])
                spine_rgba = hex_to_rgba(spine_hex, 255)
                primary_txt, secondary_txt = get_contrast_text_color(spine_hex)

                # Create individual spine image
                spine_img = Image.new("RGBA", (spine_w, spine_h), (0, 0, 0, 0))
                s_draw = ImageDraw.Draw(spine_img)

                # Base rounded top spine body
                top_rad = max(4, min(10, spine_w // 6))
                s_draw.rounded_rectangle(
                    (0, 0, spine_w - 1, spine_h + top_rad),
                    radius=top_rad,
                    fill=spine_rgba,
                )

                # 3D cylindrical highlight (left) and crease/shadow (right)
                hl_w = max(3, int(spine_w * 0.12))
                sh_w = max(4, int(spine_w * 0.14))
                s_draw.rectangle((2, 2, 2 + hl_w, spine_h), fill=(255, 255, 255, 38))
                s_draw.rectangle((spine_w - sh_w, 2, spine_w - 1, spine_h), fill=(0, 0, 0, 58))
                s_draw.line([(0, 4), (0, spine_h)], fill=(0, 0, 0, 75), width=1)
                s_draw.line([(spine_w - 1, 4), (spine_w - 1, spine_h)], fill=(0, 0, 0, 95), width=1)

                # Decorative head and tail foil bands
                band_y_top = int(spine_h * 0.06)
                band_y_bot = int(spine_h * 0.92)
                s_draw.line([(3, band_y_top), (spine_w - 4, band_y_top)], fill=secondary_txt, width=2)
                s_draw.line([(3, band_y_top + 5), (spine_w - 4, band_y_top + 5)], fill=secondary_txt, width=1)
                s_draw.line([(3, band_y_bot), (spine_w - 4, band_y_bot)], fill=secondary_txt, width=2)

                # Small cover thumbnail badge near bottom of wide spines
                text_max_len = int(spine_h * 0.76)
                if spine_w >= 46:
                    thumb_w = spine_w - 14
                    thumb_h = int(thumb_w * 1.35)
                    if thumb_h < int(spine_h * 0.22):
                        mini_cov = ImageOps.fit(
                            book["image"].convert("RGBA"),
                            (thumb_w, thumb_h),
                            Image.Resampling.LANCZOS,
                        )
                        mini_cov = add_rounded_corners(mini_cov, 4)
                        spine_img.alpha_composite(mini_cov, (7, band_y_bot - thumb_h - 10))
                        text_max_len = band_y_bot - thumb_h - band_y_top - 26

                # Vertical Spine Typography (Top-to-Bottom standard spine orientation)
                font_sz = max(12, min(int(spine_w * 0.42), int(26 * scale)))
                f_spine_title = get_font(font_sz, bold=True)
                f_spine_author = get_font(max(10, int(font_sz * 0.78)), bold=False)

                clean_title = book["title"].strip()
                author_last = book["author"].strip().split()[-1] if book.get("author", "").strip() else ""

                # Truncate title cleanly if needed to fit vertical space
                while len(clean_title) > 4:
                    tb = s_draw.textbbox((0, 0), clean_title, font=f_spine_title)
                    ab = s_draw.textbbox((0, 0), f"  •  {author_last}", font=f_spine_author) if author_last else (0, 0, 0, 0)
                    total_txt_w = (tb[2] - tb[0]) + (ab[2] - ab[0])
                    if total_txt_w <= text_max_len:
                        break
                    clean_title = clean_title[:-2].rstrip() + "…"

                # Draw horizontal text layer then rotate 270 deg (reads top-to-bottom)
                txt_layer = Image.new("RGBA", (max(10, text_max_len), spine_w), (0, 0, 0, 0))
                t_draw = ImageDraw.Draw(txt_layer)

                tb = t_draw.textbbox((0, 0), clean_title, font=f_spine_title)
                tw, th = tb[2] - tb[0], tb[3] - tb[1]
                ty = (spine_w - th) // 2 - 2
                t_draw.text((4, ty), clean_title, fill=primary_txt, font=f_spine_title)

                if author_last:
                    sep_x = 4 + tw + 10
                    ab = t_draw.textbbox((0, 0), author_last, font=f_spine_author)
                    aw, ah = ab[2] - ab[0], ab[3] - ab[1]
                    if sep_x + aw < text_max_len - 4:
                        ay = (spine_w - ah) // 2 - 1
                        t_draw.text((sep_x, ay), author_last, fill=secondary_txt, font=f_spine_author)

                rotated_txt = txt_layer.rotate(270, expand=True)
                spine_img.alpha_composite(rotated_txt, (0, band_y_top + 14))

                # Composite book spine onto shelf
                canvas.alpha_composite(spine_img, (curr_x, spine_y))
                curr_x += spine_w + 2

        # Draw wooden shelf plank across bay bottom
        draw.rectangle((inner_x, plank_top, inner_x + inner_w, bay_bottom), fill=plank_col)
        draw.rectangle((inner_x, plank_top, inner_x + inner_w, plank_top + max(4, int(5 * scale))), fill=edge_col)

    if footer_text.strip():
        footer_font = get_font(int(26 * scale), bold=False)
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - pad - int(32 * scale)),
            footer_text,
            fill=text_color,
            font=footer_font,
        )

    return canvas.convert("RGB")


def add_book_entry(meta: dict, custom_img: Image.Image | None = None):
    """Adds a standardized book dictionary (including extracted spine color) to session state."""
    if custom_img is not None:
        img = custom_img
        found = True
    elif meta.get("img_bytes"):
        img = Image.open(io.BytesIO(meta["img_bytes"]))
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
    "a **Cover Collage**, a **Reading Stats ('Wrapped')** page, and a **Bookshelf Spines** view."
)

col_left, col_right = st.columns([1.05, 1.25], gap="large")

with col_left:
    st.subheader("1. Add Your Books")

    tab_bulk, tab_single, tab_upload = st.tabs(
        ["📝 Paste Book List", "🔍 Add Single Book", "🖼️ Add Manual Book"]
    )

    with tab_bulk:
        bulk_input = st.text_area(
            "Enter one book per line (Title & Author recommended):",
            placeholder=(
                "Project Hail Mary by Andy Weir\n"
                "Tomorrow, and Tomorrow, and Tomorrow\n"
                "Dune by Frank Herbert\n"
                "Atomic Habits by James Clear"
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
        single_query = st.text_input("Book Title / Author / ISBN", placeholder="e.g., Piranesi Susanna Clarke")
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
        uploaded_file = st.file_uploader("Upload Cover Image (JPG/PNG)", type=["jpg", "jpeg", "png", "webp"])

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

    # --- MANAGE BOOKS & UPLOAD MISSING COVERS ---
    if st.session_state.books:
        st.divider()
        header_col1, header_col2 = st.columns([3, 1])
        missing_count = sum(1 for b in st.session_state.books if not b.get("found", True))
        header_col1.markdown(f"**Current Books ({len(st.session_state.books)})**")
        if header_col2.button("🗑️ Clear All"):
            st.session_state.books = []
            st.rerun()

        if missing_count > 0:
            st.warning(
                f"⚠️ {missing_count} book(s) could not find an automatic cover. "
                "Upload a replacement cover directly in the expanded box below!"
            )

        for i, b in enumerate(st.session_state.books):
            book_id = b["id"]
            if "spine_color" not in b:
                b["spine_color"] = extract_dominant_color(b["image"])

            status_icon = "✅" if b.get("found", True) else "⚠️ Missing Cover — Click to Upload"
            exp_label = f"{status_icon} **{b['title']}** — *{b['genre']} ({b['pages']}p, {b['year']})*"

            with st.expander(exp_label, expanded=not b.get("found", True)):
                top_c1, top_c2 = st.columns([1, 3])
                top_c1.image(b["image"], width=85)

                with top_c2:
                    replacement_file = st.file_uploader(
                        "📤 Upload / Replace Cover Image",
                        type=["jpg", "jpeg", "png", "webp"],
                        key=f"replace_cov_{book_id}",
                    )
                    if replacement_file is not None:
                        new_img = Image.open(replacement_file)
                        b["image"] = new_img
                        b["spine_color"] = extract_dominant_color(new_img)
                        b["found"] = True
                        st.rerun()

                    e_col1, e_col2 = st.columns(2)
                    b["title"] = e_col1.text_input("Title", value=b["title"], key=f"t_{book_id}")
                    b["author"] = e_col2.text_input("Author", value=b["author"], key=f"a_{book_id}")

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
