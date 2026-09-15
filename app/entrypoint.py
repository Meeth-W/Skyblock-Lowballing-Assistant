"""Entry script for the frozen build.

PyInstaller runs its entry script as ``__main__`` with no package around it, so
``lowball/__main__.py`` cannot be pointed at directly -- its relative imports
have nothing to resolve against and the build fails at the first line of the
first import. This imports the package properly and calls the same ``main`` the
``lowball`` console script does, so both ways in run identical code.
"""

from __future__ import annotations

import multiprocessing

from lowball.__main__ import main

if __name__ == "__main__":
    # pyqtgraph can spawn helper processes; without this the child re-runs the
    # bootloader and opens a second copy of the app instead of a worker.
    multiprocessing.freeze_support()
    raise SystemExit(main())
