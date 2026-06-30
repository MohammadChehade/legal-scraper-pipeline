"""Central configuration for the pipeline.

Every tunable value is loaded from environment variables so that no
connection string, path, or scraping parameter is hardcoded in the logic.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB client connection
    mongo_uri: str
    mongo_database: str = "legal_scraper"
    mongo_landing_collection: str = "landing_metadata"
    mongo_clean_collection: str = "clean_metadata"

    # MinIO / S3 object storage
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str
    minio_secret_key: str
    minio_region: str = "us-east-1"
    minio_landing_bucket: str = "landing-zone"
    minio_clean_bucket: str = "clean-zone"

    # Target site
    wrc_search_url: str = "https://www.workplacerelations.ie/en/search/"

    # Scraping behaviour
    partition_months: int = 1
    concurrent_requests: int = 16
    download_delay: float = 0.5
    autothrottle_enabled: bool = True
    retry_times: int = 3
    user_agent: str = "legal-scraper/0.1 (+https://example.com)"


@lru_cache
def get_settings() -> Settings:
    """Return the settings, building them once and caching the result."""
    return Settings()
