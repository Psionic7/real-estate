"""Windows Task Scheduler entry point; all paths independent of working directory."""
import os
import sys
from pathlib import Path

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
os.chdir(project)

from estate.worker import main

if __name__ == "__main__":
    sys.argv = [__file__, "--once"]
    main()
