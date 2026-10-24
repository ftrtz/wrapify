"""Round artist portraits for the listening chart, with an accent color per artist.

Vega's image mark can't clip, so the circle is baked into the image: each portrait is
fetched once, cropped to a circle with a thin ring in the artist's accent color and
embedded as a PNG data URI.
"""

import base64
import colorsys
import io
from urllib.request import urlopen

import streamlit as st
from PIL import Image, ImageDraw

# rendered at PORTRAIT_PX in the chart; drawn at 3x so it stays sharp on hi-dpi screens
PORTRAIT_PX = 26
_SCALE = 3
# accent color for artists without a (loadable) image
FALLBACK_COLOR = "#b3b3b3"


def _accent_color(img: Image.Image) -> str:
    """A frequent, saturated color of img, brightened to stand out on a dark background."""
    small = img.resize((48, 48)).quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = small.getpalette()

    def hsv(index):
        r, g, b = palette[3 * index : 3 * index + 3]
        return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    def score(entry):
        count, index = entry
        _, s, v = hsv(index)
        # near-black and near-white areas (backgrounds, shadows) say little about the image
        if v < 0.15 or (s < 0.08 and v > 0.9):
            return 0
        return count * (0.1 + s) * v

    h, s, v = hsv(max(small.getcolors(), key=score)[1])
    # a colorful image gets a clearly colored accent, a black-and-white one stays grey
    if s > 0.12:
        s = min(max(s, 0.45), 0.85)
    r, g, b = colorsys.hsv_to_rgb(h, s, max(v, 0.85))
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


@st.cache_data(ttl=86400, max_entries=500, show_spinner=False)
def portrait(url: str | None) -> tuple[str | None, str]:
    """(circular crop of the image at url as a PNG data URI, accent color).

    The data URI is None if the image can't be loaded, the color then FALLBACK_COLOR.
    """
    if not url:
        return None, FALLBACK_COLOR
    try:
        with urlopen(url, timeout=5) as resp:
            img = Image.open(io.BytesIO(resp.read())).convert("RGB")
    except (OSError, ValueError):
        return None, FALLBACK_COLOR

    color = _accent_color(img)
    size = PORTRAIT_PX * _SCALE
    # center square crop, then scale down
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, mask=mask)
    ImageDraw.Draw(out).ellipse(
        (0, 0, size - 1, size - 1), outline=color, width=round(1.5 * _SCALE)
    )

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), color
