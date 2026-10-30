"""Shared errors for the CLI entrypoint and imported capture workers."""


class BridgeError(RuntimeError):
    """Operator-safe message; never contains URLs, headers or credentials."""
