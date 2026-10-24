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
from web.portraits import PORTRAIT_PX, portrait

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
years = (
    artist_monthly.filter(pl.col("year_played") > 0)["year_played"]
    .unique()
    .sort(descending=True)
    .to_list()
)
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
        # no typing - a handful of years needs no search, and on mobile it pops up the keyboard
        filter_mode=None,
        width=160,
    )
    with st.container(
        horizontal=True,
        horizontal_alignment="right",
        vertical_alignment="center",
        width="content",
    ):
        # the total and the artists don't share a scale well, so it's one or the other
        chart_series = st.segmented_control(
            "Show",
            options=["total", "artists"],
            format_func={"total": "Total", "artists": "Top artists"}.get,
            default="total",
            required=True,
            key="chart_series",
            label_visibility="collapsed",
        )
        chart_mode = st.segmented_control(
            "Chart",
            options=["per_period", "cumulative"],
            format_func=lambda m: (
                ("Yearly" if selected_year == 0 else "Monthly")
                if m == "per_period"
                else "Cumulative"
            ),
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
first_month = (
    dated.select("year_played", "month_played").sort(["year_played", "month_played"]).row(0)
)
last_month = (
    dated.select("year_played", "month_played").sort(["year_played", "month_played"]).row(-1)
)

# Calculate total minutes per month (fill missing months within the data range with 0)
all_months = pl.DataFrame({"month_played": list(range(1, 13))})
monthly_totals = all_months.join(
    year_data.filter(pl.col("month_played") > 0)
    .group_by("month_played")
    .agg(pl.col("min_listened").sum().alias("min_total")),
    on="month_played",
    how="left",
).with_columns(
    pl.when(
        pl.lit(selected_year * 100) + pl.col("month_played") < first_month[0] * 100 + first_month[1]
    )
    .then(None)
    .when(
        pl.lit(selected_year * 100) + pl.col("month_played") > last_month[0] * 100 + last_month[1]
    )
    .then(None)
    .otherwise(pl.col("min_total").fill_null(0))
    .alias("min_total"),
    pl.col("month_played")
    .map_elements(lambda x: calendar.month_name[1:][x - 1], return_dtype=pl.Utf8)
    .alias("month_name"),
)
# Calculate total minutes per year (fill missing years with 0)
min_year = artist_monthly.filter(pl.col("year_played") > 0)["year_played"].min()
max_year = artist_monthly.filter(pl.col("year_played") > 0)["year_played"].max()
all_years = pl.DataFrame({"year_played": range(min_year, max_year + 1)})
yearly_totals = all_years.join(
    artist_monthly.filter(
        pl.col("month_played") == 0,
        pl.col("year_played") > 0,
    )
    .group_by("year_played")
    .agg(pl.col("min_listened").sum().alias("min_total")),
    on="year_played",
    how="left",
).with_columns(pl.col("min_total").fill_null(0))

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
# number of top artists drawn as lines in the chart - plus, without a selected month,
# each card's top artist not already among them
TOP_ARTIST_LINES = 5


def chart_gradient(df, x, y, color_rgb, artist_lines=None):
    """Gradient area chart; hovering marks the nearest period with a point and guide line.

    artist_lines, if given, replaces the area with one series per artist (artist_id,
    name, rank, color, x_pos, the same y column as df and a portrait data URI on its last
    point): lines in the artist's color ending in a round portrait. The hover marks them
    and the tooltip lists them, next to the period's total.
    """
    color = f"rgb({color_rgb})"
    show_artists = artist_lines is not None
    show_total = not show_artists
    if show_artists and not artist_lines.height:
        # every artist hidden: an empty chart that still has the hover and tooltip
        artist_lines = None
        show_artists = False
    if show_artists:
        # one column per artist, so the period's tooltip can list them all
        df = df.join(
            artist_lines.with_columns(pl.format("artist_{}", "rank").alias("artist_col")).pivot(
                "artist_col", index=x, values=y
            ),
            on=x,
            how="left",
        )
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
        # the artist areas overlap rather than stack
        stack=None,
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
    if show_artists:
        tooltip += [
            alt.Tooltip(f"artist_{rank}:Q", title=name, format=",d")
            for rank, name in artist_lines.select("rank", "name").unique().sort("rank").iter_rows()
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
    selectors = (
        base.mark_point(opacity=0, size=1)
        # without the area, keep them on the zero line so they don't stretch the y scale
        .encode(y_enc if show_total else alt.YDatum(0), tooltip=tooltip)
        .add_params(hover)
    )
    guide = base.mark_rule(color=color if show_total else "white", strokeDash=[3, 3]).encode(
        opacity=alt.when(hover).then(alt.value(0.5)).otherwise(alt.value(0))
    )
    point = base.mark_point(
        filled=True, size=90, color=color, stroke="white", strokeWidth=1.5
    ).encode(y_enc, opacity=alt.when(hover).then(alt.value(1)).otherwise(alt.value(0)))
    layers = [area] if show_total else []
    if show_artists:
        lines_base = alt.Chart(artist_lines).encode(base.encoding.x)
        artist_color = alt.Color("color:N", scale=None)
        lines = lines_base.mark_line(interpolate="monotone", strokeWidth=1.5, opacity=0.85).encode(
            y_enc, artist_color, detail="artist_id:N"
        )
        # the portraits sit at the end of each line and move to the hovered period: the
        # end ones show only while nothing (or their own period) is hovered
        # drawn lowest rank first, so a higher ranking artist's portrait lies on top
        portrait_order = alt.Order("rank:Q", sort="descending")
        end_portraits = (
            lines_base.transform_filter("datum.portrait != null")
            .mark_image(width=PORTRAIT_PX, height=PORTRAIT_PX)
            .encode(
                y_enc,
                url="portrait:N",
                opacity=alt.when(hover, empty=True).then(alt.value(1)).otherwise(alt.value(0)),
                order=portrait_order,
            )
        )
        # looked up per artist, so the data URIs aren't repeated on every period's row
        hover_portraits = (
            lines_base.transform_lookup(
                lookup="artist_id",
                from_=alt.LookupData(
                    artist_lines.filter(pl.col("portrait").is_not_null()).select(
                        "artist_id", pl.col("portrait").alias("hover_portrait")
                    ),
                    key="artist_id",
                    fields=["hover_portrait"],
                ),
            )
            .transform_filter("datum.hover_portrait != null")
            .mark_image(width=PORTRAIT_PX, height=PORTRAIT_PX)
            .encode(
                y_enc,
                url="hover_portrait:N",
                opacity=alt.when(hover).then(alt.value(1)).otherwise(alt.value(0)),
                order=portrait_order,
            )
        )
        # faint shading under each line (flat - a gradient can't take its color from data)
        shading = lines_base.mark_area(interpolate="monotone", opacity=0.1).encode(
            y_enc, artist_color, detail="artist_id:N"
        )
        layers += [shading, lines, end_portraits, hover_portraits]
    # selectors last, so the hover still finds the nearest period over the portraits
    return alt.layer(*layers, guide, *([point] if show_total else []), selectors)


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
if chart_series == "artists":
    # the top artists of the selected month - or of the year without one, and of all
    # years in "All years" - over the chart's periods; within the data range a period
    # without plays is 0, outside it null like the totals
    lines_month = 0 if selected_year == 0 else state.selected_month
    if selected_year == 0:
        artist_periods = artist_monthly.filter(
            pl.col("year_played") > 0, pl.col("month_played") == 0
        )
    else:
        artist_periods = year_data.filter(pl.col("month_played") > 0)
    period_ranking = year_data.filter(pl.col("month_played") == lines_month).sort(
        "min_listened", descending=True
    )
    line_artist_ids = period_ranking.head(TOP_ARTIST_LINES)["artist_id"]
    if lines_month == 0:
        card_artist_ids = (
            artist_periods.sort("min_listened", descending=True)
            .group_by(period_col)
            .first()["artist_id"]
        )
        line_artist_ids = pl.concat([line_artist_ids, card_artist_ids])
    top_line_artists = (
        period_ranking.filter(pl.col("artist_id").is_in(line_artist_ids.to_list()))
        .select("artist_id", "name", "image")
        .with_row_index("rank")
    )
    image_and_color = [portrait(url) for url in top_line_artists["image"]]
    top_line_artists = top_line_artists.with_columns(
        pl.Series("image", [uri for uri, _ in image_and_color], dtype=pl.Utf8),
        pl.Series("color", [color for _, color in image_and_color], dtype=pl.Utf8),
    )
    shown_artists = st.pills(
        "Artists in chart",
        options=top_line_artists["artist_id"].to_list(),
        format_func=dict(top_line_artists.select("artist_id", "name").iter_rows()).get,
        selection_mode="multi",
        default=top_line_artists["artist_id"].to_list(),
        # options differ per year and month
        key=f"artist_lines_{selected_year}_{lines_month}",
        label_visibility="collapsed",
    )
    artist_lines = (
        period_totals.select(period_col, "x_pos", "min_total")
        .join(top_line_artists.filter(pl.col("artist_id").is_in(shown_artists)), how="cross")
        .join(
            artist_periods.select(period_col, "artist_id", pl.col("min_listened").alias("minutes")),
            on=[period_col, "artist_id"],
            how="left",
        )
        .with_columns(
            pl.when(pl.col("min_total").is_not_null())
            .then(pl.col("minutes").fill_null(0))
            .alias("min_total")
        )
        .sort("rank", period_col)
        .with_columns(pl.col("min_total").cum_sum().over("artist_id").alias("min_cum"))
    )
    y_col = "min_cum" if chart_mode == "cumulative" else "min_total"
    # portrait on the last point of each line
    is_last = pl.col(period_col) == pl.col(period_col).filter(pl.col(y_col).is_not_null()).max()
    artist_lines = artist_lines.with_columns(
        pl.when(is_last.over("artist_id")).then(pl.col("image")).alias("portrait")
    ).drop("image", "minutes")
else:
    artist_lines = None

chart = chart_gradient(
    period_totals,
    x=period_col,
    y="min_cum" if chart_mode == "cumulative" else "min_total",
    color_rgb="29, 185, 84",
    artist_lines=artist_lines,
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
        ranked_artists_per_month = artist_monthly_selected.with_columns(
            pl.col("min_listened").rank("ordinal", descending=True).alias("rank")
        ).sort(["rank"])

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
                "followers": st.column_config.NumberColumn(
                    "👥", help="Followers", format="localized"
                ),
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
