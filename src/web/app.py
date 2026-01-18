from datetime import timedelta, date
import calendar

import streamlit as st
from streamlit_extras.mandatory_date_range import date_range_picker
from streamlit_extras.card import card
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

# for local development
from dotenv import load_dotenv

load_dotenv()

# ========== STREAMLIT CONFIG
st.set_page_config(layout="wide")

# ========== DATABASE CONNECTION
db_url = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_SECRET')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
db_schema = "prod"

# ========== LOAD DATA
artist_monthly = load_artist_monthly(db_url, db_schema)

# - LEGACY START -----------------------------------------------------------------------------------------------------------
played_raw = load_played_joined(db_url, db_schema)
artist = load_artist(db_url, db_schema)
track = load_track(db_url, db_schema)
audio_features = load_audio_features(db_url, db_schema)

# ========== DATE RANGES
min_dt = played_raw["played_at"].min().date()
max_dt = date.today() + timedelta(days=1)

state = st.session_state

# default start and end date when opening the application
if "start_date" not in state:
    state.start_date = date.today() - timedelta(days=14)

if "end_date" not in state:
    state.end_date = max_dt
# - LEGACY END -------------------------------------------------------------------------------------------------------------


with st.sidebar:
    st.header("Filter by Year")
    selected_year = st.selectbox(
        "",
        options=artist_monthly["year_played"].unique().sort(descending=True).to_list(),
        placeholder="Select Year",
    )

    if state.start_date < min_dt:
        state.start_date = min_dt


    start_date = state.start_date
    end_date = state.end_date

# Filter played data for the applied date range
if start_date and end_date:
    played = played_raw.filter(pl.col("played_at").is_between(start_date, end_date))

if played.shape[0] == 0:
    st.info("No data for the selected date range.")
else:
    # retrieve played data for artists and add artist information
    top_artists_played = get_top_artists_played(
        played, artist.with_columns(pl.col("genres").list.join(", "))
    )


    # ---------------------------------------- TRANSFORM ----------------------------------------
    # Filter data for selected year
    year_data = artist_monthly.filter(pl.col("year_played") == selected_year)

    # ---------------------------------------- OVERALL STATS CARDS ----------------------------------------
    # --- Prepare genres
    all_genres = (
        top_artists_played.select("genres")
        .with_columns(pl.col("genres").str.split(", "))
        .explode("genres")
        .drop_nulls()
        .group_by("genres")
        .len("count")
        .sort("count", descending=True)
    )
    genres_count = all_genres.shape[0]

    st.title("Spotify Dashboard")

    # --- Overall stat cards
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        with st.container(height=125, border=True):
            total_time = year_data["min_listened"].sum()
            st.metric(label="Total time listened", value=f"{int(total_time)} min")
    with c2:
        with st.container(height=125, border=True):
            st.metric(
                label="Different artists",
                value=year_data.unique("artist_id").shape[0],
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
    # ---------------------------------------- TOP ARTIST PER MONTH ----------------------------------------

    st.header("Top Artist by Month")

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

    def chart_gradient(df, y_column, color_rgb):
        chart = (
            alt.Chart(df)
            .mark_area(
                line={"color": f"rgba({color_rgb}, 1)"},
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
            )
            .encode(
                alt.X(
                    "month_played:O",
                    title=None,
                    axis=alt.Axis(
                        labelExpr=f"{calendar.month_name[1:]}[datum.value-1]", labelAngle=0
                    ),
                ),
                alt.Y(
                    f"{y_column}:Q",
                    title=None,
                    axis=alt.Axis(grid=False, labels=False, ticks=False),
                ),
                tooltip=[
                    alt.Tooltip("month_name:O", title="Month"),
                    alt.Tooltip("name:O", title="Top Artist"),
                    alt.Tooltip("min_listened:Q", title="Min listened", format=",d"),
                    alt.Tooltip("min_total:Q", title="Total min listened", format=",d"),
                ],
            )
        )
        return chart

    # Remove comments to show the monthly listened time for top and other artists
    # chart = alt.layer(
    #     chart_gradient(top_artist_per_month, "min_total", "83, 83, 83"),
    #     chart_gradient(top_artist_per_month, "min_listened", "29, 185, 84"),
    # )
    # st.altair_chart(chart, width="stretch")

    # -------- MONTHLY CARDS

    # Initialize selected month in session state (default to first month)
    months_in_data = (
        top_artist_per_month["month_played"].unique().sort(descending=False).to_list()
    )
    if "selected_month" not in state or state.selected_month not in months_in_data:
        state.selected_month = months_in_data[0] if months_in_data else None

    # Define card with selection styling
    def card_1(month_data, is_selected=False):
        card_styles = {
            "card": {
                "margin": "0",
                "width": "100%",
                "border": "3px solid #1DB954" if is_selected else "3px solid transparent",
                "border-radius": "10px",
                "box-shadow": "0 0 10px rgba(29, 185, 84, 0.5)" if is_selected else "none",
            }
        }
        card(
            title="",
            text="",
            image=month_data["image"],
            styles=card_styles,
            key=f"card_{month_data['month_played']}",
        )

    # Selection callback
    def select_month(month):
        state.selected_month = month

    cols = st.columns(len(months_in_data))

    for col_idx, month in enumerate(months_in_data):
        month_data = top_artist_per_month.filter(pl.col("month_played") == month).row(
            0, named=True
        )

        with cols[col_idx]:
            is_selected = state.selected_month == month
            card_1(month_data, is_selected=is_selected)
            st.button(
                label=calendar.month_abbr[month],
                key=f"btn_{month}",
                on_click=select_month,
                args=(month,),
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            )


    artist_monthly_selected = year_data.filter(pl.col("month_played") == state.selected_month)



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
            "followers": st.column_config.Column("👥", help="Followers"),
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


    # ---------------------------------------- TABS LAYOUT ----------------------------------------
    # t1, t2, t3 = st.tabs(["Favorites", "Metrics", "Recently Played"])
    # ---------------------------------------- TAB 1: FAVORITES ----------------------------------------

    #     # --- Artists
    #     st.header("Most Heard Artists")

    #     # prepare spotlight container on top of the table
    #     spot1, spot2, spot3 = st.columns([1, 2, 2])

    #     # Prepare ranked artists per month
    #     ranked_artists_per_month = (
    #         year_data.with_columns(
    #             pl.col("min_listened").rank("ordinal", descending=True).over("month_played").alias("rank")
    #         )
    #         .sort(["month_played", "rank"])
    #     )

    #     event = st.dataframe(
    #         ranked_artists_per_month,
    #         column_config={
    #             "rank": st.column_config.NumberColumn("🔢", format="#%d", width=15),
    #             "image": st.column_config.ImageColumn(""),
    #             "artist_id": None,
    #             "name": st.column_config.Column(""),
    #             "min_listened": st.column_config.NumberColumn(
    #                 "⏳", format="%d min", help="Time listened in minutes"
    #             ),
    #             "followers": st.column_config.Column("👥", help="Followers"),           # Info missing in data
    #             "genres": st.column_config.Column("🎶", help="Genres"),                 # Info missing in data
    #             "popularity": st.column_config.ProgressColumn(                          # Info missing in data
    #                 "🌟", format="%f", min_value=0, max_value=100, help="Popularity"
    #             ),
    #         },
    #         column_order=[
    #             "rank",
    #             "image",
    #             "name",
    #             "min_listened",
    #             "genres",
    #             "popularity",
    #             "followers",
    #         ],
    #         hide_index=True,
    #         width="stretch",
    #         on_select="rerun",
    #         selection_mode="single-row",
    #     )

    #     if event.selection.rows:
    #         selected_idx = event.selection.rows[0]
    #     else:
    #         selected_idx = 0

    #     selected_artist = top_artists_played.row(selected_idx, named=True)

    #     # --- Selected Artist Spotlight
    #     with spot1:
    #         # Image
    #         annotated_text((f"#{selected_artist['rank']}", f"{selected_artist['name']}"))

    #         st.markdown(
    #             f"""
    #             <div style="
    #                 width: 100%;
    #                 min-height: 218px;
    #                 background-image: url('{selected_artist["image"]}');
    #                 background-size: cover;
    #                 background-position: center;
    #                 border-radius: 10px;
    #             ">
    #             </div>
    #             """,
    #             unsafe_allow_html=True,
    #         )

    #     with spot2:
    #         # Cumulative Time Listened
    #         with st.container(height=260, border=True):
    #             st.caption("Cumulative Time Listened (min)")
    #             selected_cum_time = (
    #                 played.filter(pl.col("main_artist_id") == selected_artist["main_artist_id"])
    #                 .with_columns(
    #                     [
    #                         (pl.col("duration_ms") / 60000).alias("duration_min"),
    #                     ]
    #                 )
    #                 .with_columns([pl.col("duration_min").cum_sum().alias("duration_min_cumsum")])
    #             )

    #             st.altair_chart(
    #                 alt.Chart(selected_cum_time)
    #                 .mark_line()
    #                 .encode(
    #                     x=alt.X("played_at", title=None),
    #                     y=alt.Y(
    #                         "duration_min_cumsum",
    #                         axis=alt.Axis(title=None, tickMinStep=1),
    #                     ),
    #                 )
    #                 .properties(height=180),
    #                 width="stretch",
    #             )

    #     with spot3:
    #         # Most Played Tracks
    #         selected_artist_tracks = (
    #             played.filter(pl.col("main_artist_id") == selected_artist["main_artist_id"])
    #             .group_by("image", "track")
    #             .len("count")
    #             .sort(by="count", descending=True)
    #         )
    #         st.dataframe(
    #             selected_artist_tracks,
    #             column_config={
    #                 "image": st.column_config.ImageColumn("Cover"),
    #                 "track": st.column_config.Column("Title"),
    #                 "count": st.column_config.Column("Plays"),
    #             },
    #             column_order=["count", "image", "track"],
    #             hide_index=True,
    #             width="stretch",
    #             height=260,
    #         )

    #     # --- Tracks
    #     st.header("Most Played Tracks")

    #     # prepare spotlight container on top of the table
    #     spot1, spot2, spot3 = st.columns([1, 2, 2])

    #     # prepare the track data for the table
    #     top_tracks_played = get_top_tracks_played(played)

    #     event = st.dataframe(
    #         top_tracks_played,
    #         column_config={
    #             "rank": st.column_config.NumberColumn("🔢", format="#%d", width=15),
    #             "image": st.column_config.ImageColumn(""),
    #             "track_id": None,
    #             "track": st.column_config.Column("Title"),
    #             "artist": st.column_config.Column("Artist"),
    #             "album": st.column_config.Column("Album"),
    #             "popularity": st.column_config.ProgressColumn(
    #                 "🌟", format="%f", min_value=0, max_value=100, help="Popularity"
    #             ),
    #             "count": st.column_config.Column(
    #                 "Plays", help="Number of times this track was played"
    #             ),
    #             "spotify_uri": st.column_config.LinkColumn(
    #                 "▶️", help="Open in Spotify", display_text="▶️"
    #             ),
    #         },
    #         column_order=[
    #             "rank",
    #             "image",
    #             "count",
    #             "track",
    #             "artist",
    #             "album",
    #             "popularity",
    #             "spotify_uri",
    #         ],
    #         hide_index=True,
    #         width="stretch",
    #         on_select="rerun",
    #         selection_mode="single-row",
    #     )

    #     if event.selection.rows:
    #         selected_idx = event.selection.rows[0]
    #     else:
    #         selected_idx = 0

    #     selected_track = top_tracks_played.row(selected_idx, named=True)

    #     # --- Selected Track Spotlight
    #     with spot1:
    #         # Image
    #         annotated_text((f"#{selected_track['rank']}", f"{selected_track['track']}"))

    #         st.markdown(
    #             f"""
    #             <div style="
    #                 width: 100%;
    #                 min-height: 218px;
    #                 background-image: url('{selected_track["image"]}');
    #                 background-size: cover;
    #                 background-position: center;
    #                 border-radius: 10px;
    #             ">
    #             </div>
    #             """,
    #             unsafe_allow_html=True,
    #         )

    #     with spot2:
    #         # Cumulative Plays
    #         with st.container(height=282, border=True):
    #             st.caption("Cumulative Plays")

    #             selected_cum_plays = (
    #                 played.filter(pl.col("track_id") == selected_track["track_id"])
    #                 .sort("played_at")
    #                 .group_by("played_at")
    #                 .len("count")
    #                 .with_columns([pl.col("count").cum_sum().alias("cumsum")])
    #             )

    #             st.altair_chart(
    #                 alt.Chart(selected_cum_plays)
    #                 .mark_line()
    #                 .encode(
    #                     x=alt.X("played_at", title=None),
    #                     y=alt.Y("cumsum", axis=alt.Axis(title=None, tickMinStep=1)),
    #                 )
    #                 .properties(height=200),
    #                 width="stretch",
    #             )

    #     with spot3:
    #         # Audio Features
    #         selected_af = audio_features.filter(pl.col("track_id") == selected_track["track_id"])
    #         if selected_af.shape[0] == 0:
    #             st.info("Audio Features are deprecated and aren't retrieved since November 2024.")

    #         else:
    #             selected_af_pivoted = selected_af.unpivot(
    #                 index="track_id",
    #                 on=[
    #                     "acousticness",
    #                     "danceability",
    #                     "energy",
    #                     "instrumentalness",
    #                     "liveness",
    #                     "speechiness",
    #                     "valence",
    #                 ],
    #                 variable_name="Feature",
    #             )

    #             st.dataframe(
    #                 selected_af_pivoted,
    #                 column_config={
    #                     "track_id": None,
    #                     "Feature": st.column_config.Column("Audio Feature"),
    #                     "value": st.column_config.ProgressColumn(
    #                         "Value", format="%.2f", min_value=0, max_value=1
    #                     ),
    #                 },
    #                 hide_index=True,
    #                 width="stretch",
    #                 height=282,
    #             )

    #     # --- Genres
    #     st.header("Most Popular Genres")

    #     # Extract top 10 genres as list of tuples
    #     top_genres = all_genres.select(["genres", "count"]).head(10).iter_rows(named=False)

    #     # Build the converted list for annotated_text
    #     top_genres_converted = []
    #     for genre, count in top_genres:
    #         top_genres_converted.append((genre, f"{count}x"))
    #         top_genres_converted.append(" ")

    #     annotated_text(top_genres_converted)

    # # ---------------------------------------- TAB 2: METRICS ----------------------------------------
    # with t2:
    #     st.header("Artist Metrics")

    #     with st.container(border=True):
    #         # filter for artists played in time window
    #         artist_filtered = artist.join(
    #             played, how="left", left_on="id", right_on="main_artist_id"
    #         )

    #         # Create selectbox with metrics
    #         selected_metric = st.selectbox(
    #             "Select Metric", artist_filtered[["popularity", "followers"]].columns
    #         )

    #         # lookup dict for the limits of the selected metric
    #         limits = {
    #             "popularity": [0, 100],
    #             "followers": [
    #                 artist_filtered["followers"].min(),
    #                 artist_filtered["followers"].max(),
    #             ],
    #         }

    #         c1, c2 = st.columns([2, 3])
    #         with c1:
    #             selector = alt.selection_point(encodings=["x"])
    #             event = st.altair_chart(
    #                 alt.Chart(artist_filtered)
    #                 .mark_bar()
    #                 .encode(
    #                     x=alt.X(
    #                         f"{selected_metric}:Q",
    #                         bin=True,
    #                         scale=alt.Scale(domain=limits[selected_metric]),
    #                     ),
    #                     y="count(*):Q",
    #                     color=alt.condition(
    #                         selector,
    #                         f"{selected_metric}:Q",
    #                         alt.value("lightgray"),
    #                         legend=None,
    #                         sort="descending",
    #                     ),
    #                 )
    #                 .add_params(selector)
    #                 .properties(height=300),
    #                 width="stretch",
    #                 on_select="rerun",
    #             )
    #             # TODO: follower histogram should be log scale

    #         with c2:
    #             if not event["selection"]["param_1"]:
    #                 range_selection = limits[selected_metric]
    #             else:
    #                 range_selection = event["selection"]["param_1"][0][selected_metric]

    #             artist_param = artist_filtered.filter(
    #                 (pl.col(selected_metric) > range_selection[0])
    #                 & (pl.col(selected_metric) <= range_selection[1])
    #             ).sort(selected_metric, descending=True)

    #             st.dataframe(
    #                 artist_param,
    #                 column_config={
    #                     "image": st.column_config.ImageColumn("Cover"),
    #                     f"{selected_metric}": st.column_config.Column(
    #                         f"{selected_metric} ({range_selection[0]} - {range_selection[1]})"
    #                     ),
    #                     "name": st.column_config.Column("Artist"),
    #                     "id": None,
    #                     "duration_ms": None,
    #                     "album_id": None,
    #                     "album_images": None,
    #                     "uri": None,
    #                 },
    #                 hide_index=True,
    #                 width="stretch",
    #                 column_order=[selected_metric, "image", "name"],
    #                 height=300,
    #             )

    #     st.header(
    #         "Track Metrics",
    #         help="Audio Features were deprecated by Spotify. Only Tracks played before November 2024 have all Metrics.",
    #     )

    #     with st.container(border=True):
    #         # merge all played tracks with audio features
    #         p_select = played.select("track_id", "track", "artist", "popularity", "image").unique()
    #         track_full = p_select.join(audio_features, on="track_id", how="left")

    #         selected_metric = st.selectbox(
    #             "Select Metric",
    #             track_full.drop(
    #                 "track_id", "track", "artist", "image", "mode", "analysis_url"
    #             ).columns,
    #         )

    #         # lookup dict for the limits of the selected metric
    #         limits = {
    #             "popularity": [0, 100],
    #             "danceability": [0, 1],
    #             "energy": [0, 1],
    #             "key": [track_full["key"].min(), track_full["key"].max()],
    #             "loudness": [
    #                 track_full["loudness"].min(),
    #                 track_full["loudness"].max(),
    #             ],
    #             "speechiness": [0, 1],
    #             "acousticness": [0, 1],
    #             "instrumentalness": [0, 1],
    #             "liveness": [0, 1],
    #             "valence": [0, 1],
    #             "tempo": [track_full["tempo"].min(), track_full["tempo"].max()],
    #             "time_signature": [
    #                 track_full["time_signature"].min(),
    #                 track_full["time_signature"].max(),
    #             ],
    #         }

    #         c1, c2 = st.columns([2, 3])
    #         with c1:
    #             selector = alt.selection_point(encodings=["x"])
    #             event = st.altair_chart(
    #                 alt.Chart(track_full)
    #                 .mark_bar()
    #                 .encode(
    #                     x=alt.X(
    #                         f"{selected_metric}:Q",
    #                         bin=True,
    #                         scale=alt.Scale(domain=limits[selected_metric]),
    #                     ),
    #                     y="count(*):Q",
    #                     color=alt.condition(
    #                         selector,
    #                         f"{selected_metric}:Q",
    #                         alt.value("lightgray"),
    #                         legend=None,
    #                         sort="descending",
    #                     ),
    #                 )
    #                 .add_params(selector)
    #                 .properties(height=300),
    #                 width="stretch",
    #                 on_select="rerun",
    #             )

    #         with c2:
    #             if not event["selection"]["param_1"]:
    #                 range_selection = limits[selected_metric]
    #             else:
    #                 range_selection = event["selection"]["param_1"][0][selected_metric]

    #             track_param = track_full.filter(
    #                 (pl.col(selected_metric) > range_selection[0])
    #                 & (pl.col(selected_metric) <= range_selection[1])
    #             ).sort(selected_metric, descending=True)

    #             st.dataframe(
    #                 track_param,
    #                 column_config={
    #                     "image": st.column_config.ImageColumn("Cover"),
    #                     f"{selected_metric}": st.column_config.Column(
    #                         f"{selected_metric} ({range_selection[0]} - {range_selection[1]})"
    #                     ),
    #                     "track": st.column_config.Column("Title"),
    #                     "artist": st.column_config.Column("Artist"),
    #                     "id": None,
    #                     "duration_ms": None,
    #                     "album_id": None,
    #                     "album_images": None,
    #                     "uri": None,
    #                 },
    #                 hide_index=True,
    #                 width="stretch",
    #                 column_order=[selected_metric, "image", "track", "artist"],
    #                 height=300,
    #             )

    # with t3:
    #     st.header("Recently Played Tracks")

    #     recently_played = played.sort(by="played_at", descending=True)

    #     st.dataframe(
    #         recently_played,
    #         column_config={
    #             "played_at": st.column_config.DatetimeColumn("Played at"),
    #             "image": st.column_config.ImageColumn(""),
    #             "track_id": None,
    #             "track": st.column_config.Column("Title"),
    #             "artist": st.column_config.Column("Artist"),
    #             "album": st.column_config.Column("Album"),
    #             "popularity": st.column_config.ProgressColumn(
    #                 "🌟", format="%f", min_value=0, max_value=100, help="Popularity"
    #             ),
    #             "spotify_uri": st.column_config.LinkColumn(
    #                 "▶️", help="Open in Spotify", display_text="▶️"
    #             ),
    #         },
    #         column_order=[
    #             "played_at",
    #             "image",
    #             "track",
    #             "artist",
    #             "album",
    #             "popularity",
    #             "spotify_uri",
    #         ],
    #         hide_index=True,
    #         width="stretch",
    #     )
