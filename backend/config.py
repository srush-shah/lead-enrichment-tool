from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    census_api_key: str = ""
    newsapi_key: str = ""
    gemini_api_key: str = ""

    webhook_shared_secret: str = "dev-secret"
    cache_db_path: str = "./cache.db"
    log_level: str = "INFO"

    # Web app session auth (Next.js -> backend).
    nextauth_secret: str = "dev-nextauth-secret"
    allowed_emails: str = ""  # comma-separated allowlist; empty = open for local dev


settings = Settings()


# NMHC Top-25 apartment markets (public, defensible industry standard).
# Source: NMHC 50 Largest Apartment Markets.
TOP_25_MSAS = frozenset({
    "New York-Newark-Jersey City",
    "Dallas-Fort Worth-Arlington",
    "Houston-The Woodlands-Sugar Land",
    "Atlanta-Sandy Springs-Alpharetta",
    "Los Angeles-Long Beach-Anaheim",
    "Washington-Arlington-Alexandria",
    "Chicago-Naperville-Elgin",
    "Phoenix-Mesa-Chandler",
    "Miami-Fort Lauderdale-Pompano Beach",
    "Boston-Cambridge-Newton",
    "Seattle-Tacoma-Bellevue",
    "San Francisco-Oakland-Berkeley",
    "Austin-Round Rock-Georgetown",
    "Denver-Aurora-Lakewood",
    "Minneapolis-St. Paul-Bloomington",
    "Tampa-St. Petersburg-Clearwater",
    "Orlando-Kissimmee-Sanford",
    "San Diego-Chula Vista-Carlsbad",
    "Philadelphia-Camden-Wilmington",
    "Charlotte-Concord-Gastonia",
    "Nashville-Davidson-Murfreesboro-Franklin",
    "Raleigh-Cary",
    "Portland-Vancouver-Hillsboro",
    "San Antonio-New Braunfels",
    "Las Vegas-Henderson-Paradise",
})

# Rough city -> MSA mapping so we can match from raw lead input without a geocoder lookup.
# Covers the NMHC top-25 metros; anything not in this table is treated as non-top-25.
CITY_TO_MSA = {
    "new york": "New York-Newark-Jersey City",
    "brooklyn": "New York-Newark-Jersey City",
    "queens": "New York-Newark-Jersey City",
    "bronx": "New York-Newark-Jersey City",
    "newark": "New York-Newark-Jersey City",
    "jersey city": "New York-Newark-Jersey City",
    "dallas": "Dallas-Fort Worth-Arlington",
    "fort worth": "Dallas-Fort Worth-Arlington",
    "arlington": "Dallas-Fort Worth-Arlington",
    "plano": "Dallas-Fort Worth-Arlington",
    "houston": "Houston-The Woodlands-Sugar Land",
    "sugar land": "Houston-The Woodlands-Sugar Land",
    "atlanta": "Atlanta-Sandy Springs-Alpharetta",
    "sandy springs": "Atlanta-Sandy Springs-Alpharetta",
    "alpharetta": "Atlanta-Sandy Springs-Alpharetta",
    "los angeles": "Los Angeles-Long Beach-Anaheim",
    "long beach": "Los Angeles-Long Beach-Anaheim",
    "anaheim": "Los Angeles-Long Beach-Anaheim",
    "washington": "Washington-Arlington-Alexandria",
    "alexandria": "Washington-Arlington-Alexandria",
    "chicago": "Chicago-Naperville-Elgin",
    "naperville": "Chicago-Naperville-Elgin",
    "phoenix": "Phoenix-Mesa-Chandler",
    "mesa": "Phoenix-Mesa-Chandler",
    "chandler": "Phoenix-Mesa-Chandler",
    "miami": "Miami-Fort Lauderdale-Pompano Beach",
    "fort lauderdale": "Miami-Fort Lauderdale-Pompano Beach",
    "boston": "Boston-Cambridge-Newton",
    "cambridge": "Boston-Cambridge-Newton",
    "seattle": "Seattle-Tacoma-Bellevue",
    "tacoma": "Seattle-Tacoma-Bellevue",
    "bellevue": "Seattle-Tacoma-Bellevue",
    "san francisco": "San Francisco-Oakland-Berkeley",
    "oakland": "San Francisco-Oakland-Berkeley",
    "berkeley": "San Francisco-Oakland-Berkeley",
    "austin": "Austin-Round Rock-Georgetown",
    "round rock": "Austin-Round Rock-Georgetown",
    "denver": "Denver-Aurora-Lakewood",
    "aurora": "Denver-Aurora-Lakewood",
    "minneapolis": "Minneapolis-St. Paul-Bloomington",
    "st. paul": "Minneapolis-St. Paul-Bloomington",
    "saint paul": "Minneapolis-St. Paul-Bloomington",
    "tampa": "Tampa-St. Petersburg-Clearwater",
    "st. petersburg": "Tampa-St. Petersburg-Clearwater",
    "orlando": "Orlando-Kissimmee-Sanford",
    "san diego": "San Diego-Chula Vista-Carlsbad",
    "philadelphia": "Philadelphia-Camden-Wilmington",
    "charlotte": "Charlotte-Concord-Gastonia",
    "nashville": "Nashville-Davidson-Murfreesboro-Franklin",
    "raleigh": "Raleigh-Cary",
    "portland": "Portland-Vancouver-Hillsboro",
    "san antonio": "San Antonio-New Braunfels",
    "las vegas": "Las Vegas-Henderson-Paradise",
    "henderson": "Las Vegas-Henderson-Paradise",
}


# Free webmail domains -- signal of non-institutional lead.
FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "icloud.com", "protonmail.com", "mail.com",
    "live.com", "msn.com", "ymail.com",
})


# Scoring weights (see docs/ASSUMPTIONS.md for rationale).
MPS_WEIGHTS = {"p5plus": 0.50, "walkscore": 0.25, "density": 0.15, "renter": 0.10}
PRE_SCORE_WEIGHTS = {"mps": 0.60, "market_fit": 0.25, "domain": 0.15}
FULL_SCORE_WEIGHTS = {"market_fit": 0.35, "company_fit": 0.30, "timing": 0.20, "geographic": 0.15}

# Gates.
MPS_SKIP_THRESHOLD = 50      # below this -> Review Queue, no S2/S3.
PRE_SCORE_S2_GATE = 50       # need this to unlock NewsAPI + Wikipedia.
FULL_SCORE_S3_GATE = 70      # need this to unlock Gemini drafting.

# Free-tier budgets (batch reserves; onEdit gets the remainder).
NEWSAPI_DAILY_CAP = 100
NEWSAPI_BATCH_CEILING = 85
# gemini-2.5-flash free tier is ~250 RPD / 10 RPM as of 2026-04. Some accounts
# see tighter project-level caps (we observed `limit: 20` in a 429). Set the
# daily cap to the documented value and a defensive 6.0s gap so the quota
# gate actually trips before the API does.
GEMINI_DAILY_CAP = 250
GEMINI_BATCH_CEILING = 220
GEMINI_MIN_GAP_SECONDS = 6.5  # 6.0s puts us right at the 10 RPM cap; 6.5s = 9.2 RPM gives jitter headroom

# Tier thresholds for Full Score (only applied when MPS >= skip threshold).
TIER_A_MIN = 80
TIER_B_MIN = 60
TIER_C_MIN = 40
