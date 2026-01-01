from pydantic_settings import BaseSettings
from pathlib import Path
import os

class Settings(BaseSettings):
    IG_USERNAME: str
    IG_PASSWORD: str

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    SESSION_DIR: Path = BASE_DIR / "sessions"
    SESSION_FILE: Path = os.path.join(SESSION_DIR, "ig_session.json")

    DOWNLOAD_DIR: Path = os.path.join(BASE_DIR, "downloads")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
