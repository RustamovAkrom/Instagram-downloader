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

import instaloader
import os
from dotenv import load_dotenv
from app.config import settings

load_dotenv()

settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)

proxy_url = (
    f"http://brd-customer-hl_0793675b-zone-scraping_browser1:"
    f"pxyyd378gevm@"
    f"brd.superproxy.io:"
    f"9222"
)

L = instaloader.Instaloader()

# 🔥 КЛЮЧЕВОЕ
L.context._session.proxies = {
    "http": proxy_url,
    "https": proxy_url,
}

L.login(
    os.getenv("IG_USERNAME"),
    os.getenv("IG_PASSWORD")
)

L.save_session_to_file(filename=str(settings.SESSION_FILE))
print("✅ Session saved with proxy:", settings.SESSION_FILE)
