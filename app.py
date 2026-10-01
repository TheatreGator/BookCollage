import io
import math
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Book Collage Maker",
    page_icon="📚",
    layout="wide",
)

# --- SESSION STATE INITIALIZATION ---
if "books" not in st.session_state:
    # Each item: {"title": str, "author": str, "image": PIL.Image}
    st.session_state.books = []


# --- HELPER FUNCTIONS ---
def create_placeholder_cover(title: str, author: str = "") -> Image.Image:
    """Generates a clean fallback cover if an online cover cannot be found."""
    width, height = 400, 600
    img = Image.new("RGB", (width, height), color=(58, 79, 65))
    draw = ImageDraw.Draw(img)

    # Decorative border
    draw.rectangle([20, 20, width - 20, height - 20], outline=(230, 220, 200), width=3)

    try:
        font_title = ImageFont.load_default(size=28)
        font_author = ImageFont.load_default(size=20)
    except TypeError:
        font_title = ImageFont.load_default()
        font_author = ImageFont.load_default()

    # Wrap title text roughly
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


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_book_cover(query: str):
    """
    Searches Open Library first, then Google Books as a fallback.
    Returns (title, author, bytes_of_image_or_None).
    """
    headers = {"User-Agent": "BookCollageStreamlitApp/1.0"}

    # 1. Try Open Library API
    try:
        ol_url = "https://openlibrary.org/search.json"
        resp = requests.get(ol_url, params={"q": query, "limit": 5}, headers=headers, timeout=8)
        if resp.status_code == 200:
            docs = resp.json().get("docs", [])
            for doc in docs:
                cover_id = doc.get("cover_i")
                if cover_id:
                    img_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
                    img_resp = requests.get(img_url, headers=headers, timeout=8)
                    if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                        title = doc.get("title", query)
                        authors = doc.get("author_name", [""])
                        return title, authors[0], img_resp.content
    except Exception:
        pass

    # 2. Fallback to Google Books API
    try:
        gb_url = "https://www.googleapis.com/books/v1/volumes"
        resp = requests.get(gb_url, params={"q": query, "maxResults": 3}, headers=headers, timeout=8)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            for item in items:
                vol = item.get("volumeInfo", {})
                image_links = vol.get("imageLinks", {})
                thumb = image_links.get("thumbnail") or image_links.get("smallThumbnail")
                if thumb:
                    # Request higher resolution zoom where available
                    high_res_url = thumb.replace("http://", "https://").replace("&edge=curl", "")
                    img_resp = requests.get(high_res_url, headers=headers, timeout=8)
                    if img_resp.status_code == 200:
                        title = vol.get("title", query)
                        authors = vol.get("authors", [""])
                        return title, authors[0], img_resp.content
    except Exception:
        pass

    return query, "", None


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

    # Reserve vertical space for header & footer
    top_offset = margin + (110 if header_text.strip() else 0)
    bottom_offset = margin + (70 if footer_text.strip() else 0)

    avail_w = max(100, canvas_w - (2 * margin) - ((cols - 1) * gap))
    avail_h = max(100, canvas_h - top_offset - bottom_offset - ((rows - 1) * gap))

    # Standard book aspect ratio ~ 2:3 (width:height = 1:1.5)
    book_aspect = 1.5
    cell_w = avail_w / cols
    cell_h = avail_h / rows

    if cell_w * book_aspect <= cell_h:
        cover_w = int(cell_w)
        cover_h = int(cell_w * book_aspect)
    else:
        cover_h = int(cell_h)
        cover_w = int(cell_h / book_aspect)

    # Total grid dimensions to center the block nicely
    total_grid_h = rows * cover_h + (rows - 1) * gap
    start_y = top_offset + (avail_h - total_grid_h) // 2

    # Draw Header Text
    if header_text.strip():
        try:
            header_font = ImageFont.load_default(size=52)
        except TypeError:
            header_font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), header_text, font=header_font)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_w - tw) / 2, margin + 15), header_text, fill=text_color, font=header_font)

    # Draw Footer Text
    if footer_text.strip():
        try:
            footer_font = ImageFont.load_default(size=30)
        except TypeError:
            footer_font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((canvas_w - tw) / 2, canvas_h - margin - 45),
            footer_text,
            fill=text_color,
            font=footer_font,
        )

    # Render each book cover
    for idx, book in enumerate(books):
        r = idx // cols
        c = idx % cols

        # Center incomplete last row
        items_in_this_row = cols if (r < rows - 1 or n_books % cols == 0) else (n_books % cols)
        row_width = items_in_this_row * cover_w + (items_in_this_row - 1) * gap
        start_x = (canvas_w - row_width) // 2

        x = start_x + c * (cover_w + gap)
        y = start_y + r * (cover_h + gap)

        # Resize & crop cover cleanly to 2:3 ratio
        cover_img = ImageOps.fit(book["image"].convert("RGBA"), (cover_w, cover_h), Image.Resampling.LANCZOS)
        cover_img = add_rounded_corners(cover_img, corner_radius)

        # Optional drop shadow
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


# --- UI LAYOUT ---
st.title("📚 Social Media Book Collage Maker")
st.markdown("Type in the books you've read to generate a shareable cover collage for Instagram, TikTok, Goodreads, or X.")

col_left, col_right = st.columns([1, 1.3], gap="large")

with col_left:
    st.subheader("1. Add Your Books")

    tab_bulk, tab_single, tab_upload = st.tabs(["📝 Paste Book List", "🔍 Add Single Book", "🖼️ Upload Custom Cover"])

    with tab_bulk:
        bulk_input = st.text_area(
            "Enter one book per line (Title & Author recommended):",
            placeholder="Project Hail Mary by Andy Weir\nTomorrow, and Tomorrow, and Tomorrow\nDune by Frank Herbert\nThe Secret History by Donna Tartt",
            height=150,
        )
        if st.button("✨ Fetch Covers from List", type="primary", use_container_width=True):
            lines = [line.strip() for line in bulk_input.split("\n") if line.strip()]
            if lines:
                progress = st.progress(0, text="Fetching book covers...")
                for i, line in enumerate(lines):
                    title, author, img_bytes = fetch_book_cover(line)
                    if img_bytes:
                        img = Image.open(io.BytesIO(img_bytes))
                    else:
                        img = create_placeholder_cover(title, author)
                    st.session_state.books.append({"title": title, "author": author, "image": img})
                    progress.progress((i + 1) / len(lines), text=f"Loaded: {title}")
                progress.empty()
                st.rerun()

    with tab_single:
        single_query = st.text_input("Book Title / Author / ISBN", placeholder="e.g., Piranesi Susanna Clarke")
        if st.button("Add Book", use_container_width=True) and single_query.strip():
            with st.spinner("Searching cover..."):
                title, author, img_bytes = fetch_book_cover(single_query.strip())
                if img_bytes:
                    img = Image.open(io.BytesIO(img_bytes))
                else:
                    img = create_placeholder_cover(title, author)
                st.session_state.books.append({"title": title, "author": author, "image": img})
                st.rerun()

    with tab_upload:
        custom_title = st.text_input("Book Title (Optional)", placeholder="My Custom Book")
        uploaded_file = st.file_uploader("Upload Cover Image (JPG/PNG)", type=["jpg", "jpeg", "png", "webp"])
        if st.button("Add Uploaded Cover", use_container_width=True) and uploaded_file is not None:
            img = Image.open(uploaded_file)
            st.session_state.books.append({"title": custom_title or uploaded_file.name, "author": "", "image": img})
            st.rerun()

    # Manage current list of books
    if st.session_state.books:
        st.divider()
        header_col1, header_col2 = st.columns([3, 1])
        header_col1.markdown(f"**Current Books ({len(st.session_state.books)})**")
        if header_col2.button("🗑️ Clear All"):
            st.session_state.books = []
            st.rerun()

        for i, b in enumerate(st.session_state.books):
            c1, c2, c3, c4 = st.columns([1, 4, 1, 1])
            c1.image(b["image"], width=40)
            c2.markdown(f"**{b['title']}**  \n<small>{b['author']}</small>", unsafe_allow_html=True)
            if c3.button("⬆️", key=f"up_{i}", disabled=(i == 0)):
                st.session_state.books[i - 1], st.session_state.books[i] = (
                    st.session_state.books[i],
                    st.session_state.books[i - 1],
                )
                st.rerun()
            if c4.button("✖️", key=f"del_{i}"):
                st.session_state.books.pop(i)
                st.rerun()

    st.divider()
    st.subheader("2. Customize Layout")

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

    # Calculate smart default columns
    n_books = max(1, len(st.session_state.books))
    default_cols = min(6, max(1, int(math.ceil(math.sqrt(n_books)))))

    s_col1, s_col2 = st.columns(2)
    cols = s_col1.slider("Columns", min_value=1, max_value=8, value=default_cols)
    gap = s_col2.slider("Spacing Between Covers", min_value=0, max_value=80, value=28)

    s_col3, s_col4 = st.columns(2)
    margin = s_col3.slider("Outer Margin", min_value=20, max_value=200, value=70)
    corner_radius = s_col4.slider("Corner Rounding", min_value=0, max_value=40, value=12)

    t_col1, t_col2 = st.columns(2)
    header_text = t_col1.text_input("Header Title (Optional)", placeholder="e.g., October Reads")
    footer_text = t_col2.text_input("Footer Text (Optional)", placeholder="e.g., @mybookgram")

    c_col1, c_col2, c_col3 = st.columns(3)
    bg_color = c_col1.color_picker("Background Color", "#F5F2EB")
    text_color = c_col2.color_picker("Text Color", "#2C2623")
    add_shadow = c_col3.checkbox("3D Drop Shadow", value=True)

with col_right:
    st.subheader("3. Preview & Export")

    if not st.session_state.books:
        st.info("👈 Add some books on the left to generate your collage preview!")
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

        # Convert to bytes for download
        buf = io.BytesIO()
        collage_img.save(buf, format="PNG", quality=95)
        byte_im = buf.getvalue()

        st.download_button(
            label="📥 Download High-Res PNG for Social Media",
            data=byte_im,
            file_name="my_book_collage.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
        )

        st.image(collage_img, caption=f"Preview ({canvas_size[0]}x{canvas_size[1]} px)", use_container_width=True)

