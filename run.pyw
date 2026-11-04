import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdfdesk.__main__ import main

sys.exit(main())
