"""Small Streamlit widgets used by the dashboard.

These live here instead of coming from `streamlit-extras`, which pulls in
plotly, matplotlib, snowflake-snowpark and botocore (~200MB) for the two
helpers the dashboard actually used.
"""

from datetime import date, timedelta
from typing import Any, Optional, Tuple, cast

import streamlit as st


def date_range_picker(
    title: str,
    default_start: Optional[date] = None,
    default_end: Optional[date] = None,
    min_date: Optional[date] = None,
    max_date: Optional[date] = None,
    error_message: str = "Please select start and end date",
    **kwargs: Any,
) -> Tuple[date, date]:
    """Like `st.date_input` with a range, but always returns both dates.

    `st.date_input` reruns the app as soon as the first date is clicked, yielding
    a single-element tuple. This stops the app until the user has picked both.
    """
    if default_start is None:
        default_start = date.today() - timedelta(days=30)
    if default_end is None:
        default_end = date.today()

    val = st.date_input(
        title,
        value=[default_start, default_end],
        min_value=min_date,
        max_value=max_date,
        **kwargs,
    )

    try:
        start_date, end_date = cast(Tuple[date, date], val)
    except ValueError:
        st.error(error_message)
        st.stop()

    return start_date, end_date
