"""`python -m grep_analyzer` エントリ。"""

import sys

from grep_analyzer.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
