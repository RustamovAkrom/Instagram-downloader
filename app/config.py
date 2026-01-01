from dotenv import load_dotenv
import os


load_dotenv()

class Settings:
    IG_USERNAME: str = os.getenv("IG_USERNAME")
    IG_PASSWORD: str = os.getenv("IG_PASSWORD")
    DOWNLOAD_DIR: str = os.getenv("DOWNLOAD_DIR", "downloads")
            
settings = Settings()
            