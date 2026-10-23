create schema if not exists {{ analytics_schema }};

-- create artists_listened_monthly table
drop table if exists {{ analytics_schema }}.artists_listened_monthly;

create table if not exists {{ analytics_schema }}.artists_listened_monthly (
    primary key(year_played, month_played, artist_id),
    year_played int not null,
    month_played int not null,
    -- exact sum of track durations; consumers convert to minutes (ms / 60000.0)
    ms_listened bigint not null,
    artist_id VARCHAR not null references {{ prod_schema }}.artist(id),
    name varchar not null,
    image varchar,
    popularity int not null,
    followers int not null,
    genres text[],
    created timestamp with time zone default now(),
    updated timestamp with time zone default now()
);
