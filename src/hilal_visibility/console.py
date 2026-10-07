"""UTF-8 terminal output for the interactive and script entry points."""

import sys


def configure_console_encoding():
    """Keep scientific symbols intact on consoles and redirected output.

    StringIO and host-provided streams without reconfigure remain supported.
    This is called at entry points, so importing the calculation library does
    not change the caller's stream configuration.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8')
