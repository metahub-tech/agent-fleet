import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))                           # server dir
sys.path.insert(0, str(_here.parent.parent.parent / "common"))  # platforms/common
