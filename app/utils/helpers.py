from urllib.parse import urlparse


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
        return parts[1]
    raise ValueError("Invalid Instagram URL. URL must contain /p/, /reel/ or /tv/")

