"""Launch the MusicReviver desktop application."""

from src.runtime import initialize_standard_streams

initialize_standard_streams()

from src.gui.app import main


if __name__ == "__main__":
    raise SystemExit(main())
