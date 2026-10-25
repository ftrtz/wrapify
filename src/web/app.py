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

if "selected_month" not in state:
    state.selected_month = default_month(state.selected_year)
# the year picker is drawn in the chart fragment below - a year change reruns the app
selected_year = state.selected_year

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
    # not map_elements with a lambda: polars caches the functions it is given, and a new
    # lambda per rerun kept every rerun's globals - all its DataFrames - alive
    pl.col("month_played")
    .replace_strict(dict(enumerate(calendar.month_name)), return_dtype=pl.Utf8)
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

# ---------------------------------------- CHART ----------------------------------------
# fewest artists drawn as lines in the chart: each card's top artist and the
# period's top artist, topped up with its next top artists if that's fewer
MIN_ARTIST_LINES = 5


def chart_gradient(df, x, y, color_rgb, artist_lines=None, portraits=None):
    """Gradient area chart; hovering marks the nearest period with a point and guide line.

    artist_lines, if given, replaces the area with one series per artist (artist_id,
    name, rank, color, x_pos, the period columns, the same y column as df and line_end,
    true on its last point): lines in the artist's color ending in a round portrait -
    from portraits (artist_id, portrait_url as a data URI), one row per artist.
    Hovering then picks the nearest artist's point - its portrait moves there and the
    tooltip shows just that artist.

    A tap selects the same way and stays selected (only a mouse leaving clears it), so
    the chart works on touch screens. Vega hides its tooltip as the finger lifts, so a
    touch selection gets a label at the top of the chart instead.
    """
    color = f"rgb({color_rgb})"
    show_artists = artist_lines is not None
    show_total = not show_artists
    if show_artists and not artist_lines.height:
        # every artist hidden: an empty chart that still has the hover and tooltip
        artist_lines = None
        show_artists = False

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
    period_tooltip = (
        alt.Tooltip("month_name:O", title="Month")
        if x == "month_played"
        else alt.Tooltip("year_played:O", title="Year")
    )
    select_on = "pointerover, click"
    clear_on = "pointerout[event.pointerType === 'mouse']"
    tap_on = "click[event.pointerType !== 'mouse']"

    def touch_label(chart, tap, name_expr=None):
        """The tooltip's content as a line of text beside the guide, at the top of the
        chart - for the point selected by tap, which only touch selects."""
        period = "slice(datum.month_name, 0, 3)" if x == "month_played" else "datum.year_played"
        parts = [
            *([name_expr] if name_expr else []),
            period,
            "format(datum.min_total, ',d') + ' min'",
            "format(datum.min_cum, ',d') + ' total'",
        ]
        right = "datum.x_pos > 0.5"
        return (
            chart.transform_calculate(label=" + ' · ' + ".join(parts))
            .mark_text(
                baseline="top",
                fontSize=11,
                color="white",
                align=alt.expr(f"{right} ? 'right' : 'left'"),
                dx=alt.expr(f"{right} ? -6 : 6"),
            )
            .encode(
                y=alt.value(0),
                text="label:N",
                opacity=alt.when(tap).then(alt.value(0.9)).otherwise(alt.value(0)),
            )
        )

    if show_artists:
        # nearest artist point to the pointer: hover marks that point, artist_hover its
        # artist (to fade the others) and period_hover its period (to move every
        # portrait there)
        hover = alt.selection_point(
            fields=[x, "artist_id"],
            nearest=True,
            on=select_on,
            clear=clear_on,
            empty=False,
        )
        tap = alt.selection_point(
            fields=[x, "artist_id"], nearest=True, on=tap_on, clear=clear_on, empty=False
        )
        artist_hover = alt.selection_point(
            fields=["artist_id"], nearest=True, on=select_on, clear=clear_on, empty=False
        )
        period_hover = alt.selection_point(
            # named, for the "nothing hovered" test on its store below
            name="period_hover",
            fields=[x],
            nearest=True,
            on=select_on,
            clear=clear_on,
            empty=False,
        )
        lines_base = alt.Chart(artist_lines).encode(base.encoding.x)
        artist_color = alt.Color("color:N", scale=None)

        # while an artist is hovered, the others fade
        def unless_other_hovered(opacity, faded):
            return (
                alt.when(artist_hover, empty=True)
                .then(alt.value(opacity))
                .otherwise(alt.value(faded))
            )

        lines = lines_base.mark_line(interpolate="monotone", strokeWidth=1.5).encode(
            y_enc, artist_color, detail="artist_id:N", opacity=unless_other_hovered(0.85, 0.2)
        )
        # faint shading under each line (flat - a gradient can't take its color from data)
        shading = lines_base.mark_area(interpolate="monotone").encode(
            y_enc, artist_color, detail="artist_id:N", opacity=unless_other_hovered(0.1, 0.03)
        )
        # the portraits, looked up per artist so the data URIs aren't repeated on every
        # period's row: at the end of each line, or while hovering all at the hovered
        # period - the hovered artist's in full, the others faded like their lines
        portraits_base = (
            lines_base.transform_lookup(
                lookup="artist_id",
                from_=alt.LookupData(
                    portraits.filter(pl.col("portrait_url").is_not_null()),
                    key="artist_id",
                    fields=["portrait_url"],
                ),
            )
            .transform_filter("datum.portrait_url != null")
            .mark_image(width=PORTRAIT_PX, height=PORTRAIT_PX)
        )
        portraits = portraits_base.encode(
            y_enc,
            url="portrait_url:N",
            opacity=alt.when(hover)
            # the hovered artist's is drawn by hovered_portrait, on top of all others
            .then(alt.value(0))
            .when(period_hover)
            .then(alt.value(0.35))
            # nothing hovered: the line ends
            .when("!length(data('period_hover_store')) && datum.line_end")
            .then(alt.value(1))
            .otherwise(alt.value(0)),
            # drawn lowest rank first, so a higher ranking artist's portrait lies on top
            order=alt.Order("rank:Q", sort="descending"),
        )
        hovered_portrait = portraits_base.encode(
            y_enc,
            url="portrait_url:N",
            opacity=alt.when(hover).then(alt.value(1)).otherwise(alt.value(0)),
        )
        guide = lines_base.mark_rule(color="white", strokeDash=[3, 3]).encode(
            opacity=alt.when(hover).then(alt.value(0.5)).otherwise(alt.value(0))
        )
        # invisible points that pick up the pointer (nearest=True) and carry the tooltip
        selectors = (
            lines_base.mark_point(opacity=0, size=1)
            .encode(
                y_enc,
                tooltip=[
                    alt.Tooltip("name:N", title="Artist"),
                    period_tooltip,
                    alt.Tooltip("min_total:Q", title="Min listened", format=",d"),
                    alt.Tooltip("min_cum:Q", title="Running total", format=",d"),
                ],
            )
            .add_params(hover, artist_hover, period_hover, tap)
        )
        label = touch_label(lines_base, tap, name_expr="datum.name")
        # selectors last, so the hover still finds the nearest point over the portraits
        return alt.layer(shading, lines, guide, portraits, hovered_portrait, label, selectors)

    # nearest period to the pointer; empty=False so nothing is marked until hovering
    hover = alt.selection_point(fields=[x], nearest=True, on=select_on, clear=clear_on, empty=False)
    tap = alt.selection_point(fields=[x], nearest=True, on=tap_on, clear=clear_on, empty=False)
    tooltip = [
        period_tooltip,
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
    selectors = (
        base.mark_point(opacity=0, size=1)
        # without the area, keep them on the zero line so they don't stretch the y scale
        .encode(y_enc if show_total else alt.YDatum(0), tooltip=tooltip)
        .add_params(hover, tap)
    )
    guide = base.mark_rule(color=color if show_total else "white", strokeDash=[3, 3]).encode(
        opacity=alt.when(hover).then(alt.value(0.5)).otherwise(alt.value(0))
    )
    point = base.mark_point(
        filled=True, size=90, color=color, stroke="white", strokeWidth=1.5
    ).encode(y_enc, opacity=alt.when(hover).then(alt.value(1)).otherwise(alt.value(0)))
    layers = [area] if show_total else []
    label = touch_label(base, tap)
    return alt.layer(*layers, guide, *([point] if show_total else []), label, selectors)


@st.fragment
def listening_chart():
    """Year picker, chart controls and the chart. A fragment, so switching the series
    or mode or toggling artists redraws just the chart; a new year reruns the app."""
    # year picker left, chart mode right; fixed widths so neither gets squeezed on narrow screens
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        st.selectbox(
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
        if state.selected_year != selected_year:
            # everything below the chart depends on the year too
            st.rerun()
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
        # each card's top artist plus the top artists of the year - of all years in
        # "All years" - over the chart's periods, the same whichever month is selected;
        # within the data range a period without plays is 0, outside it null like the totals
        if selected_year == 0:
            artist_periods = artist_monthly.filter(
                pl.col("year_played") > 0, pl.col("month_played") == 0
            )
        else:
            artist_periods = year_data.filter(pl.col("month_played") > 0)
        period_ranking = year_data.filter(pl.col("month_played") == 0).sort(
            "min_listened", descending=True
        )
        line_artist_ids = set(
            artist_periods.sort("min_listened", descending=True)
            .group_by(period_col)
            .first()["artist_id"]
        )
        # the year's top artist always, then its next ones until there are enough lines
        for i, artist_id in enumerate(period_ranking["artist_id"]):
            if i and len(line_artist_ids) >= MIN_ARTIST_LINES:
                break
            line_artist_ids.add(artist_id)
        top_line_artists = (
            period_ranking.filter(pl.col("artist_id").is_in(line_artist_ids))
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
            # options differ per year
            key=f"artist_lines_{selected_year}",
            label_visibility="collapsed",
        )
        artist_lines = (
            # the period columns too, for the tooltip (monthly data has a month name)
            period_totals.select(
                period_col,
                *(["month_name"] if period_col == "month_played" else []),
                "x_pos",
                "min_total",
            )
            .join(
                top_line_artists.filter(pl.col("artist_id").is_in(shown_artists)).drop("image"),
                how="cross",
            )
            .join(
                artist_periods.select(
                    period_col, "artist_id", pl.col("min_listened").alias("minutes")
                ),
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
        artist_lines = artist_lines.with_columns(is_last.over("artist_id").alias("line_end")).drop(
            "minutes"
        )
        # kept apart from artist_lines: a data URI column there - even null on all but
        # the last points - shares one string buffer that is sent along with every row
        portraits = top_line_artists.select("artist_id", pl.col("image").alias("portrait_url"))
    else:
        artist_lines = portraits = None

    chart = chart_gradient(
        period_totals,
        x=period_col,
        y="min_cum" if chart_mode == "cumulative" else "min_total",
        color_rgb="29, 185, 84",
        artist_lines=artist_lines,
        portraits=portraits,
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


listening_chart()


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
