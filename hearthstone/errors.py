"""Atomic resolution guards shared by the interpreter and scheduler."""


class ResolutionLimitError(RuntimeError):
    """A bounded sequence failed; the caller's input state is unchanged."""
