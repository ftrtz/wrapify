from datetime import timedelta, date
import calendar

import streamlit as st
from streamlit_card import card
from annotated_text import annotated_text
import altair as alt
import polars as pl
import os

from web.load_tables import (
    load_played_joined,
    load_artist,
    load_track,
    load_audio_features,
    load_artist_monthly,
)
from web.transform_tables import get_top_artists_played, get_top_tracks_played
from web.widgets import date_range_picker

# for local development
from dotenv import load_dotenv

load_dotenv()

# ========== STREAMLIT CONFIG
st.set_page_config(layout="wide")

# ========== DATABASE CONNECTION
db_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_SECRET')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
prod_schema = "prod"
stats_schema = "stats"

# ========== LOAD DATA
# --- From stats schema
artist_monthly = load_artist_monthly(db_url, stats_schema)
# --- From prod schema
played_raw = load_played_joined(db_url, prod_schema)
artist = load_artist(db_url, prod_schema)
track = load_track(db_url, prod_schema)
audio_features = load_audio_features(db_url, prod_schema)

# ---------------------------------------- DASHBOARD ----------------------------------------
st.title("Spotify Dashboard")

with st.columns([1, 8])[0]:
    selected_year = st.selectbox(
        "",
        options=artist_monthly["year_played"].unique().sort(descending=True).to_list(),
        placeholder="Select Year",
    )

# ---------------------------------------- APPLY FILTERS ----------------------------------------
# --- YEAR SELECTION
year_data = artist_monthly.filter(pl.col("year_played") == selected_year)

# Calculate total minutes per month
monthly_totals = year_data.group_by("month_played").agg(
    pl.col("min_listened").sum().alias("min_total")
)

# Get top artist per month (highest min_listened)
top_artist_per_month = (
    year_data.sort("min_listened", descending=True)
    .group_by("month_played")
    .first()
    .join(monthly_totals, on="month_played")
    .with_columns(
        (pl.col("min_total") - pl.col("min_listened")).alias("min_others"),
        pl.col("month_played")
        .map_elements(lambda x: calendar.month_name[1:][x - 1], return_dtype=pl.Utf8)
        .alias("month_name"),
    )
    .sort("month_played")
)

# --- MONTH SELECTION

# Initialize selected month in session state (default to January)
state = st.session_state

if "selected_month" not in state:
    state.selected_month = 1

# ---------------------------------------- MONTHLY CARDS ----------------------------------------

# Define card with selection styling
def card_1(month: int, month_data: dict | None, is_selected: bool = False):
    card_styles = {
        "card": {
            "margin": "0",
            "width": "100%",
            "border": "3px solid #1DB954" if is_selected else "3px solid transparent",
            "border-radius": "10px",
            "box-shadow": "0 0 10px rgba(0,0,0,0.5)",
        },
        "filter": {
            "background-color": "rgba(0, 0, 0, 0)"  # <- make the image not dimmed anymore
        },
    }
    card(
        title="",
        text="",
        image=month_data["image"],
        styles=card_styles,
        key=f"card_{month}",
    )

# Selection callback (toggle behavior: clicking selected month deselects it)
def select_month(month):
    if state.selected_month == month:
        state.selected_month = 0
    else:
        state.selected_month = month

column_widths = [2 if month == state.selected_month else 1 for month in range(1, 13)]
cols = st.columns(column_widths)

for col_idx, month in enumerate(range(1, 13)):
    # Get month data if available
    month_df = top_artist_per_month.filter(pl.col("month_played") == month)
    month_data = month_df.row(0, named=True) if month_df.shape[0] > 0 else None

    with cols[col_idx]:
        is_selected = state.selected_month == month
        if month_data:
            card_1(month, month_data, is_selected=is_selected)
            st.button(
                label=calendar.month_abbr[month],
                key=f"btn_{month}",
                on_click=select_month,
                args=(month,),
                use_container_width=True,
                type="primary" if is_selected else "secondary",
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
        st.header(f"Spotify Stats for {selected_year}")
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
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        with st.container(height=125, border=True):
            total_time = artist_monthly_selected["min_listened"].sum()
            st.metric(label="Total time listened", value=f"{int(total_time)} min")
    with c2:
        with st.container(height=125, border=True):
            st.metric(
                label="Different artists",
                value=artist_monthly_selected.unique("artist_id").shape[0],
            )
    with c3:
        with st.container(height=125, border=True):
            st.metric(label="Different genres", value=genres_count)
    with c4:
        with st.container(height=125, border=True):
            st.metric(label="Different tracks", value=played.unique("track_id").shape[0])
    with c5:
        with st.container(height=125, border=True):
            avg_pop = played.unique("track_id")["popularity"].mean()
            st.metric(
                label="Average popularity of tracks",
                value=round(avg_pop, 2),
                delta=round(avg_pop - track["popularity"].mean(), 2),
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
                    "⏳", format="%d min", help="Time listened in minutes"
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
