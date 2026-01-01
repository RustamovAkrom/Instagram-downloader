import instaloader
import os
from dotenv import load_dotenv

load_dotenv()

L = instaloader.Instaloader()
L.login(os.getenv("IG_USERNAME"), os.getenv("IG_PASSWORD"))
L.save_session_to_file()
print("✅ Session saved")
