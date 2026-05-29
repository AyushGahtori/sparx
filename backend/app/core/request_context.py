from contextvars import ContextVar, Token


_request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
_client_ip_context: ContextVar[str | None] = ContextVar("client_ip", default=None)


def set_request_context(request_id: str | None, client_ip: str | None) -> tuple[Token, Token]:
    request_token = _request_id_context.set(request_id)
    client_token = _client_ip_context.set(client_ip)
    return request_token, client_token


def reset_request_context(tokens: tuple[Token, Token]) -> None:
    request_token, client_token = tokens
    _request_id_context.reset(request_token)
    _client_ip_context.reset(client_token)


def get_request_id() -> str | None:
    return _request_id_context.get()


def get_client_ip() -> str | None:
    return _client_ip_context.get()
