# import instaloader
# import os
# from dotenv import load_dotenv
# from app.config import settings
# load_dotenv()

# settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)

# L = instaloader.Instaloader()
# L.login(os.getenv("IG_USERNAME"), os.getenv("IG_PASSWORD"))
# L.save_session_to_file(filename=str(settings.SESSION_FILE))
# print("✅ Session saved:", settings.SESSION_FILE)
