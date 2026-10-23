"""Row of cards showing the top artist per period (month or year); click a card to select it.

Built on Streamlit's Custom Components v2: plain HTML/CSS/JS rendered in the page
(no iframe), with clicks sent back to Python as a trigger.
"""

from pathlib import Path
from typing import Callable

import streamlit as st

_DIR = Path(__file__).parent

# Gap between cards as a fraction of the row width. A percentage (not rem) keeps the
# single-row layout proportional at any width, so card_centers can predict where each
# card sits and the chart above can line its points up with them.
CARD_GAP = 0.007


def card_centers(ids: list[int], selected: int) -> dict[int, float]:
    """Horizontal center of each card as a fraction (0-1) of the row width.

    Mirrors the wide layout in style.css: cards share the row after gaps, and the
    selected card is twice as wide (flex-grow 2).
    """
    weights = [2 if i == selected else 1 for i in ids]
    available = 1 - CARD_GAP * (len(ids) - 1)
    centers, x = {}, 0.0
    for i, w in zip(ids, weights):
        width = available * w / sum(weights)
        centers[i] = x + width / 2
        x += width + CARD_GAP
    return centers


_component = st.components.v2.component(
    "artist_cards",
    css=(_DIR / "style.css").read_text(),
    js=(_DIR / "main.js").read_text(),
)


def artist_cards(items: list[dict], selected: int, key: str, on_click: Callable[[int], None]):
    """Render one card per period.

    Args:
        items: One dict per period with keys id (month or year number), label (badge
            text) and name (full name for the tooltip), plus - for periods with data -
            artist, image, minutes, share (percent) and top_track. Periods without an
            artist are shown as disabled placeholders.
        selected: id of the card to highlight, 0 for none.
        key: Unique widget key.
        on_click: Called with the clicked card's id.
    """

    def handle_click():
        clicked = st.session_state[key].clicked
        if clicked:
            on_click(clicked)

    _component(
        key=key,
        data={"items": items, "selected": selected, "gap": CARD_GAP},
        on_clicked_change=handle_click,
    )
