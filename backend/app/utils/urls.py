from urllib.parse import urlparse, urlunparse


def to_websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("PUBLIC_BASE_URL must use http or https.")

    websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(parsed._replace(scheme=websocket_scheme))
