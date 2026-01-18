from fastapi import FastAPI, Query, HTTPException
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn
import os
from datetime import datetime
from typing import Annotated

app = FastAPI(title="Spotify Listening Stats API")

# Build DATABASE_URL from individual environment variables
POSTGRES_USER = os.getenv("POSTGRES_USER", "db_user")
POSTGRES_SECRET = os.getenv("POSTGRES_SECRET", "db_password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "spotify")

DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_SECRET}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@app.get("/top-artist")
def get_top_artist(
    year: Annotated[int, Query(description="Year of interest (e.g. 2023)")] = datetime.now().year,
    month: Annotated[int, Query(description="Month of interest (1-12)")] = datetime.now().month,
):
    """
    Returns the most listened artist for a given year and month
    """
    query = text("""
        select
            year_played,
            month_played,
            artist_id,
            name,
            image,
            sec_listened/60 as min_listened
        from stats.artists_listened_monthly
        where year_played = :year
            and month_played = :month
        order by sec_listened desc
        limit 1;
    """)

    with SessionLocal() as session:
        result = session.execute(query, {"year": year, "month": month}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="No data found for given year-month")

    return {
        "year": year,
        "month": month,
        "artist_id": result.artist_id,
        "name": result.name,
        "image": result.image,
        "min_listened": int(result.min_listened),
    }


if __name__ == "__main__":
    uvicorn.run(app=app, host="0.0.0.0", port=8000)
