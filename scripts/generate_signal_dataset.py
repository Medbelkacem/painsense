#!/usr/bin/env python

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dataset.synthetic.signals import main

if __name__ == "__main__":
    main()
