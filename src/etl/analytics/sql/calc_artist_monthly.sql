
with played_artists as (
	select
		date_part('year', p.played_at) as year_played,
		date_part('month', p.played_at) as month_played,
		p.track_id,
		t.duration_ms,
		a.artist_id
	from {{ prod_schema }}.played p
	inner join {{ prod_schema }}.track t
		on p.track_id  = t.id
	inner join {{ prod_schema }}.track_artist a
		on p.track_id = a.track_id
	where a.artist_position = 0
),

calc as (
	select
		coalesce(year_played, 0) as year_played,
		coalesce(month_played, 0) as month_played,
		artist_id,
		sum(duration_ms) as ms_listened
	from played_artists
	group by
		rollup(year_played, month_played),
		artist_id
),

artist_info as (
	select
		artist_stats.year_played,
		artist_stats.month_played,
		artist_stats.ms_listened,
		artist_stats.artist_id,
		artist.name,
		artist.images->1->'url'->>0 as image,
		artist.popularity,
		artist.followers,
		artist.genres
	from calc artist_stats
	inner join {{ prod_schema }}.artist artist
		on artist_stats.artist_id = artist.id
)

insert into {{ analytics_schema }}.artists_listened_monthly
select * from artist_info;
