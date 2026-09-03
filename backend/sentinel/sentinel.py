import sys
from pathlib import Path

# Fix sys.path to allow running this script directly without shadowing the package
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / 'sentinel') in sys.path:
    sys.path.remove(str(ROOT / 'sentinel'))
if len(sys.path) > 0 and sys.path[0] == str(Path(__file__).resolve().parent):
    sys.path.pop(0)
sys.path.insert(0, str(ROOT))

from sentinel.cli import main

if __name__ == "__main__":
    main()
