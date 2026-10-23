"""Row of cards showing the top artist per period (month or year); click a card to select it.

Built on Streamlit's Custom Components v2: plain HTML/CSS/JS rendered in the page
(no iframe), with clicks sent back to Python as a trigger.
"""

from pathlib import Path
from typing import Callable

import streamlit as st

_DIR = Path(__file__).parent

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
        data={"items": items, "selected": selected},
        on_clicked_change=handle_click,
    )
