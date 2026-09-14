"""The Qt interface.

Deliberately thin: importing this package must not pull in the main window,
because the window imports the controller and the controller imports from
here. Import :mod:`lowball.ui.main_window` directly when you need it.
"""

from .theme import stylesheet
from .workers import AsyncBridge

__all__ = ["AsyncBridge", "stylesheet"]
