from fastapi import Request


def resolve_client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"
