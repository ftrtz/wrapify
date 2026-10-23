from datetime import date
import calendar

import streamlit as st
import altair as alt
import polars as pl
import os

from web.load_tables import (
    load_played_joined,
    load_artist,
    load_audio_features,
    load_artist_monthly,
)
from web.transform_tables import get_top_artists_played
from web.artist_cards import artist_cards, card_centers

# for local development - python-dotenv is a dev dependency, absent from the web image
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ========== STREAMLIT CONFIG
st.set_page_config(layout="wide")

# ========== DATABASE CONNECTION
db_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_SECRET')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
prod_schema = "prod"
# set ANALYTICS_SCHEMA=stats_dev locally to read stats built by a local analytics run
stats_schema = os.getenv("ANALYTICS_SCHEMA", "stats")

# ========== LOAD DATA
# --- From stats schema
artist_monthly = load_artist_monthly(db_url, stats_schema)
# --- From prod schema
played_raw = load_played_joined(db_url, prod_schema)
artist = load_artist(db_url, prod_schema)
audio_features = load_audio_features(db_url, prod_schema)

# ---------------------------------------- DASHBOARD ----------------------------------------
st.title("Spotify Dashboard")

state = st.session_state


def default_month(year: int) -> int:
    """Current month in the current year, no month (whole year) in any other."""
    today = date.today()
    return today.month if year == today.year else 0


def reset_month():
    state.selected_month = default_month(state.selected_year)


def select_year(year: int):
    state.selected_year = year
    reset_month()


# year 0 is the analytics rollup over all years - listed first, but the page opens
# on the latest year (set via session state rather than option order)
years = artist_monthly.filter(pl.col("year_played") > 0)["year_played"].unique().sort(descending=True).to_list()
if "selected_year" not in state:
    state.selected_year = years[0]

# year picker left, chart mode right; fixed widths so neither gets squeezed on narrow screens
with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    selected_year = st.selectbox(
        "Year",
        options=[0, *years],
        key="selected_year",
        on_change=reset_month,
        label_visibility="collapsed",
        format_func=lambda y: "All years" if y == 0 else str(y),
        placeholder="Select Year",
        width=160,
    )
    chart_mode = st.segmented_control(
        "Chart",
        options=["per_period", "cumulative"],
        format_func=lambda m: ("Yearly" if selected_year == 0 else "Monthly")
        if m == "per_period"
        else "Cumulative",
        default="per_period",
        required=True,
        key="chart_mode",
        label_visibility="collapsed",
    )

# ---------------------------------------- APPLY FILTERS ----------------------------------------
# --- YEAR SELECTION
year_data = artist_monthly.filter(pl.col("year_played") == selected_year)

# First and last month with any data, as (year, month) - months outside this range
# have no data yet (or anymore) rather than zero listening, so they stay null
dated = artist_monthly.filter(pl.col("year_played") > 0, pl.col("month_played") > 0)
first_month = dated.select("year_played", "month_played").sort(["year_played", "month_played"]).row(0)
last_month = dated.select("year_played", "month_played").sort(["year_played", "month_played"]).row(-1)

# Calculate total minutes per month (fill missing months within the data range with 0)
all_months = pl.DataFrame({"month_played": list(range(1, 13))})
monthly_totals = (
    all_months
    .join(
        year_data
        .filter(pl.col("month_played") > 0)
        .group_by("month_played")
        .agg(pl.col("min_listened").sum().alias("min_total")),
        on="month_played",
        how="left",
    )
    .with_columns(
        pl.when(
            pl.lit(selected_year * 100) + pl.col("month_played")
            < first_month[0] * 100 + first_month[1]
        )
        .then(None)
        .when(
            pl.lit(selected_year * 100) + pl.col("month_played")
            > last_month[0] * 100 + last_month[1]
        )
        .then(None)
        .otherwise(pl.col("min_total").fill_null(0))
        .alias("min_total"),
        pl.col("month_played")
        .map_elements(lambda x: calendar.month_name[1:][x - 1], return_dtype=pl.Utf8)
        .alias("month_name"),
    )
)
# Calculate total minutes per year (fill missing years with 0)
min_year = artist_monthly.filter(pl.col("year_played") > 0)["year_played"].min()
max_year = artist_monthly.filter(pl.col("year_played") > 0)["year_played"].max()
all_years = pl.DataFrame({"year_played": range(min_year, max_year + 1)})
yearly_totals = (
    all_years
    .join(
        artist_monthly
        .filter(
            pl.col("month_played") == 0,
            pl.col("year_played") > 0,
        )
        .group_by("year_played")
        .agg(pl.col("min_listened").sum().alias("min_total")),
        on="year_played",
        how="left",
    )
    .with_columns(pl.col("min_total").fill_null(0))
)

# Get top artist per month (highest min_listened)
top_artist_per_month = (
    year_data.sort("min_listened", descending=True)
    .filter(pl.col("month_played") > 0)
    .group_by("month_played")
    .first()
)

# --- MONTH SELECTION
if "selected_month" not in state:
    state.selected_month = default_month(selected_year)

# ---------------------------------------- CHART ----------------------------------------
def chart_gradient(df, x, y, color_rgb):
    """Gradient area chart; hovering marks the nearest period with a point and guide line."""
    color = f"rgb({color_rgb})"
    # nearest period to the pointer; empty=False so nothing is marked until hovering
    hover = alt.selection_point(
        fields=[x], nearest=True, on="pointerover", clear="pointerout", empty=False
    )

    base = alt.Chart(df).encode(
        # each point sits at the center of its card below (x_pos, 0-1 of the row
        # width), so the curve stretches around the wider selected card too
        alt.X(
            "x_pos:Q",
            title=None,
            scale=alt.Scale(domain=[0, 1], nice=False, zero=False),
            # no x labels - the cards below name each month/year, and the tooltip too
            axis=None,
        ),
    )
    # subtle y axis: a few faint dashed gridlines with small labels drawn inside the
    # plot (left-aligned just above each line), so the chart keeps its full width
    y_enc = alt.Y(
        f"{y}:Q",
        title=None,
        axis=alt.Axis(
            tickCount=3,
            domain=False,
            ticks=False,
            tickSize=0,
            grid=True,
            gridColor="white",
            gridOpacity=0.08,
            gridDash=[2, 4],
            labelAlign="left",
            labelBaseline="bottom",
            labelPadding=-4,
            labelFontSize=10,
            labelOpacity=0.5,
            # "2k"; no label on the zero line
            labelExpr="datum.value ? format(datum.value, '~s') : ''",
        ),
    )
    # monthly data has no year column and yearly data no month name
    tooltip = [
        alt.Tooltip("month_name:O", title="Month")
        if x == "month_played"
        else alt.Tooltip("year_played:O", title="Year"),
        alt.Tooltip("min_total:Q", title="Min listened", format=",d"),
        alt.Tooltip("min_cum:Q", title="Running total", format=",d"),
    ]

    area = base.mark_area(
        line={"color": color},
        interpolate="monotone",
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color=f"rgba({color_rgb}, 0)", offset=0),
                alt.GradientStop(color=f"rgba({color_rgb}, 0.7)", offset=1),
            ],
            x1=1,
            x2=1,
            y1=1,
            y2=0,
        ),
    ).encode(y_enc)
    # invisible points that pick up the pointer (nearest=True) and carry the tooltip
    selectors = base.mark_point(opacity=0, size=1).encode(y_enc, tooltip=tooltip).add_params(hover)
    guide = base.mark_rule(color=color, strokeDash=[3, 3]).encode(
        opacity=alt.when(hover).then(alt.value(0.5)).otherwise(alt.value(0))
    )
    point = base.mark_point(filled=True, size=90, color=color, stroke="white", strokeWidth=1.5).encode(
        y_enc, opacity=alt.when(hover).then(alt.value(1)).otherwise(alt.value(0))
    )
    return alt.layer(area, guide, point, selectors)


period_col = "year_played" if selected_year == 0 else "month_played"
period_totals = yearly_totals if selected_year == 0 else monthly_totals
centers = card_centers(
    period_totals[period_col].to_list(),
    selected=0 if selected_year == 0 else state.selected_month,
)
period_totals = period_totals.with_columns(
    # running total; null (no data yet) stays null so the curve still stops there
    pl.col("min_total").cum_sum().alias("min_cum"),
    pl.col(period_col).replace_strict(centers, return_dtype=pl.Float64).alias("x_pos"),
)
chart = chart_gradient(
    period_totals,
    x=period_col,
    y="min_cum" if chart_mode == "cumulative" else "min_total",
    color_rgb="29, 185, 84",
)
period_word = "year" if selected_year == 0 else "month"
# Hide the chart's hover toolbar (table/download/fullscreen) - not needed here, and it
# floats over the chart mode toggle. No native option exists, so scope a CSS rule to
# this chart via its container key (.st-key-listening_chart).
st.html(
    "<style>.st-key-listening_chart [data-testid='stElementToolbar'] { display: none; }</style>"
)
with st.container(key="listening_chart"):
    st.altair_chart(
        chart,
        height=200,
        width="stretch",
        alt=f"Minutes listened per {period_word}"
        if chart_mode == "per_period"
        else f"Cumulative minutes listened by {period_word}",
    )

# ---------------------------------------- MONTHLY CARDS ----------------------------------------

# Selection callback (toggle behavior: clicking selected month deselects it)
def select_month(month):
    if state.selected_month == month:
        state.selected_month = 0
    else:
        state.selected_month = month


def build_cards(
    period: str,
    periods: list[int],
    top_artists: pl.DataFrame,
    totals: pl.DataFrame,
    plays: pl.DataFrame,
    label,
    name,
) -> list[dict]:
    """One card per period (month or year) with its top artist.

    `period` is the column holding the period in top_artists and totals; plays
    needs that column too, derived from played_at.
    """
    # Most played track of each period's top artist (by play count, ties go to the
    # most recently played - otherwise the pick changes between reruns)
    top_track = dict(
        plays.join(
            top_artists.select(period, pl.col("artist_id").alias("main_artist_id")),
            on=[period, "main_artist_id"],
        )
        .group_by(period, "track")
        .agg(pl.len().alias("plays"), pl.col("played_at").max().alias("last_played"))
        .sort(["plays", "last_played"], descending=True)
        .group_by(period)
        .first()
        .select(period, "track")
        .iter_rows()
    )
    total = dict(totals.select(period, "min_total").drop_nulls().iter_rows())
    top_by_period = {r[period]: r for r in top_artists.iter_rows(named=True)}

    cards = []
    for p in periods:
        card = {"id": p, "label": label(p), "name": name(p)}
        if top := top_by_period.get(p):
            card |= {
                "artist": top["name"],
                "image": top["image"],
                "minutes": round(top["min_listened"]),
                "share": round(100 * top["min_listened"] / total[p]) if total.get(p) else 0,
                "top_track": top_track.get(p),
            }
        cards.append(card)
    return cards


if selected_year == 0:
    # one card per year; clicking one opens that year
    top_artist_per_year = (
        artist_monthly.filter(pl.col("month_played") == 0, pl.col("year_played") > 0)
        .sort("min_listened", descending=True)
        .group_by("year_played")
        .first()
    )
    artist_cards(
        build_cards(
            "year_played",
            # full range, so a year without plays shows as a placeholder like a month does
            list(range(min_year, max_year + 1)),
            top_artist_per_year,
            yearly_totals,
            played_raw.with_columns(pl.col("played_at").dt.year().alias("year_played")),
            label=str,
            name=str,
        ),
        selected=0,
        key="artist_cards_years",
        on_click=select_year,
    )
else:
    artist_cards(
        build_cards(
            "month_played",
            list(range(1, 13)),
            top_artist_per_month,
            monthly_totals,
            played_raw.filter(pl.col("played_at").dt.year() == selected_year).with_columns(
                pl.col("played_at").dt.month().alias("month_played")
            ),
            label=lambda m: calendar.month_abbr[m],
            name=lambda m: calendar.month_name[m],
        ),
        selected=state.selected_month,
        # one widget per year, so a click is never compared against another year's state
        key=f"artist_cards_{selected_year}",
        on_click=select_month,
    )

# ---------------------------------------- PREPARE SELECTED MONTH DATA ----------------------------------------

# Filter played data for the applied date range
if selected_year == 0:
    # year
    start_year = artist_monthly.filter(pl.col("year_played") > 0)["year_played"].min()
    end_year = artist_monthly["year_played"].max()
    # month
    start_month = 1
    end_month = 12
    state.selected_month = 0
else:
    start_year = selected_year
    end_year = selected_year
    if state.selected_month == 0:
        # whole year
        start_month = 1
        end_month = 12
    else:
        # specific month
        start_month = state.selected_month
        end_month = state.selected_month

start_date = date(start_year, start_month, 1)
end_date = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])

played = played_raw.filter(pl.col("played_at").is_between(start_date, end_date))
if played.shape[0] == 0:
    st.info("No data for the selected date range.")
else:
    # retrieve played data for artists and add artist information
    top_artists_played = get_top_artists_played(
        played, artist.with_columns(pl.col("genres").list.join(", "))
    )


    artist_monthly_selected = year_data.filter(pl.col("month_played") == state.selected_month)

    # ---------------------------------------- STATS CARDS ----------------------------------------

    if state.selected_month == 0:
        year_text = selected_year if selected_year > 0 else "All Years"
        st.header(f"Spotify Stats for {year_text}")
    else:
        st.header(f"Spotify Stats for {calendar.month_name[state.selected_month]}, {selected_year}")

    # --- Prepare genres
    all_genres = (
        artist_monthly_selected.select("genres")
        .explode("genres")
        .drop_nulls()
        .group_by("genres")
        .len("count")
        .sort("count", descending=True)
    )
    genres_count = all_genres.shape[0]

    # --- Overall stat cards
    # Average over plays (a track played 50 times counts 50 times), skipping
    # popularity 0 - Spotify reports 0 for tracks no longer available, not for
    # unpopular ones, and ~28% of tracks have it
    def avg_popularity(plays: pl.DataFrame) -> float | None:
        return plays.filter(pl.col("popularity") > 0)["popularity"].mean()

    avg_pop = avg_popularity(played)
    avg_all = avg_popularity(played_raw)
    # compared against all plays - except in "All years", where that's the value
    # itself; None when every play in the period has popularity 0
    pop_delta = (
        round(avg_pop - avg_all, 1)
        if selected_year != 0 and avg_pop is not None and avg_all is not None
        else None
    )

    # bordered metrics with height="stretch" all match the tallest card in the row
    # (the popularity card, with its delta) instead of scrolling inside a fixed height
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        # unit in the label - "348,118 min" is too wide for the card and gets cut off
        label="Minutes listened",
        value=round(artist_monthly_selected["min_listened"].sum()),
        format="localized",
        border=True,
        height="stretch",
    )
    c2.metric(
        label="Different artists",
        value=artist_monthly_selected.unique("artist_id").shape[0],
        format="localized",
        border=True,
        height="stretch",
    )
    c3.metric(
        label="Different genres",
        value=genres_count,
        format="localized",
        border=True,
        height="stretch",
    )
    c4.metric(
        label="Different tracks",
        value=played.unique("track_id").shape[0],
        format="localized",
        border=True,
        height="stretch",
    )
    c5.metric(
        label="Track popularity",
        value=None if avg_pop is None else round(avg_pop, 1),
        delta=pop_delta,
        delta_description=None if pop_delta is None else "vs. all time",
        # more mainstream isn't better or worse, so no green/red
        delta_color="off",
        help="Spotify popularity (0-100) of what you played, averaged over "
        "plays - tracks you replay count more. Tracks Spotify reports as 0 "
        "(usually no longer available) are left out.",
        border=True,
        height="stretch",
    )

    # ---------------------------------------- ARTISTS ----------------------------------------
    st.subheader(f"Top Artists")

    if artist_monthly_selected.shape[0] == 0:
        st.info("No data available for the current selection.")
    else:
        ranked_artists_per_month = (
            artist_monthly_selected.with_columns(
                pl.col("min_listened").rank("ordinal", descending=True).alias("rank")
            )
            .sort(["rank"])
        )

        event = st.dataframe(
            ranked_artists_per_month,
            column_config={
                "rank": st.column_config.NumberColumn("🔢", format="#%d", width=15),
                "image": st.column_config.ImageColumn(""),
                "artist_id": None,
                "name": st.column_config.Column(""),
                "min_listened": st.column_config.NumberColumn(
                    "⏳", format="%.0f min", help="Time listened in minutes"
                ),
                "genres": st.column_config.Column("🎶", help="Genres"),
                "popularity": st.column_config.ProgressColumn(
                    "🌟", format="%f", min_value=0, max_value=100, help="Popularity"
                ),
                "followers": st.column_config.NumberColumn("👥", help="Followers", format="localized"),
            },
            column_order=[
                "rank",
                "image",
                "name",
                "min_listened",
                "genres",
                "popularity",
                "followers",
            ],
            hide_index=True,
            width="stretch",
            on_select="rerun",
            selection_mode="single-row",
        )
