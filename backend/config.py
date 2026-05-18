from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    abaqus_mode: str = "mock"
    abaqus_path: str = ""
    work_dir: str = "./output_dir"
    watch_dir: str = "./watch_dir"
    output_dir: str = "./output_dir"
    database_url: str = "postgresql://feauser:feapass@localhost:5432/fea_automation"
    redis_url: str = "redis://localhost:6379"
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
