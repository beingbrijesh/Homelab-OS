"""Allow execution via `python3 -m homelab_os`."""

import sys
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
