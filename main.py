"""Top-level launcher. Run `python main.py` (or the packaged app)."""
import multiprocessing

if __name__ == "__main__":
    # Full-library scans recycle short-lived metadata parser processes.  This
    # must run before importing Qt/PyInstaller application modules so spawned
    # children do not accidentally launch a second GUI.
    multiprocessing.freeze_support()
    from lyon.app import main

    raise SystemExit(main())
