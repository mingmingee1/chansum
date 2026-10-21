class WorkError(Exception):
    def __init__(self, code: str, message: str, transient=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.transient = transient


class Cancelled(Exception):
    pass
