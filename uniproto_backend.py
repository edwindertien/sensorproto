"""
uniproto_backend.py — auto-select matplotlib backend for macOS/Windows/Linux.
Import this before importing matplotlib.pyplot:

    import uniproto_backend   # noqa
    import matplotlib.pyplot as plt
"""
import sys
import matplotlib

if sys.platform == "darwin":
    try:
        matplotlib.use("MacOSX")
    except Exception:
        matplotlib.use("TkAgg")
else:
    # Windows and Linux: prefer Qt5, fall back to Tk
    for backend in ("Qt5Agg", "TkAgg", "Agg"):
        try:
            matplotlib.use(backend)
            break
        except Exception:
            continue