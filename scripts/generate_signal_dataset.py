#!/usr/bin/env python

import sys
from pathlib import Path

# The generators live under dataset/ at the repository root, which is not on the path
# when this file is run as a script.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset.synthetic.signals import main  # noqa: E402

if __name__ == "__main__":
    main()
