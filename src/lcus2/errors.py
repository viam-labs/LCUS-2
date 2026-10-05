"""Errors raised by the LCUS-2 driver."""


class Lcus2Error(Exception):
    """The relay board could not be opened or did not accept a command."""
