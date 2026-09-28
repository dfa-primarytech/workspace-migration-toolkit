class ToolkitError(Exception):
    """An error with an explicitly safe public message (never parser/API details)."""

    def __init__(self, code: str, message: str, status: int = 400, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        # A short, non-sensitive hint for the report (e.g. "http_429"). Never the
        # response body: only something that says which way the failure went.
        self.detail = detail
