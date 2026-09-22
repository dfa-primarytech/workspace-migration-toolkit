class ToolkitError(Exception):
    """An error with an explicitly safe public message (never parser/API details)."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
