"""決定的合成ソース木生成（同一シード同一木・spec v4 §4 WS6）。"""

import random
from pathlib import Path

_JAVA = "class C{0}{{ static final int S{0}={1}; int u{0}=S{2}; }}\n"
_C = "static int s{0}={1};\nint u{0}=s{2};\n"
_SH = "S{0}={1}\necho $S{2}\n"


def generate(root: Path, *, seed: int, n_files: int) -> None:
    root = Path(root)
    rnd = random.Random(seed)               # シード固定＝決定的
    for i in range(n_files):
        kind = i % 3
        d = root / f"pkg{i % 5}"
        d.mkdir(parents=True, exist_ok=True)
        ref = rnd.randint(0, max(0, i))
        if kind == 0:
            (d / f"C{i}.java").write_text(_JAVA.format(i, rnd.randint(1, 9), ref), "utf-8")
        elif kind == 1:
            (d / f"c{i}.c").write_text(_C.format(i, rnd.randint(1, 9), ref), "utf-8")
        else:
            (d / f"s{i}.sh").write_text(_SH.format(i, rnd.randint(1, 9), ref), "utf-8")
