"""wheelhouse/*.whl から pkg==ver --hash=sha256 を生成（spec §4.1/WS5）。"""

import hashlib
import re
import sys
from pathlib import Path

WH = Path("wheelhouse")
out = []
for whl in sorted(WH.glob("*.whl")):
    m = re.match(r"([A-Za-z0-9_.]+)-([0-9][^-]*)-", whl.name)
    if not m:
        print(f"skip(命名不一致): {whl.name}", file=sys.stderr)
        continue
    pkg, ver = m.group(1).replace("_", "-"), m.group(2)
    sha = hashlib.sha256(whl.read_bytes()).hexdigest()
    out.append(f"{pkg}=={ver} --hash=sha256:{sha}")
Path("requirements.lock").write_text("\n".join(out) + "\n", "utf-8")
print(f"requirements.lock 生成: {len(out)} packages")
