"""wheelhouse/*.whl から pkg==ver --hash=sha256 を生成（spec §4.1/WS5）。

多アーキ同梱対応: 同一 pkg==ver に複数 wheel（x86_64/aarch64 等）が在る場合は
1 行に複数 --hash を集約する（pip --require-hashes は同一行複数 hash を許容し、
実行プラットフォーム適合 wheel を選択）。完全バージョンピン（spec §4.1）の不変条件
として、1 パッケージに複数バージョンが在れば異常終了する。

前提（既知の限界・現 wheelhouse では非該当）: wheel 名は PEP 427 準拠で
パッケージ名/版が正規表記であること。版の PEP 440 正規化（例 `1.0` と
`1.0.0` の同一視）や名前の PEP 503 完全正規化（`.`→`-`）・ビルドタグは
扱わない。同一 pkg の2アーキ wheel が版表記を違える等が起きた場合は
「完全ピン違反」として安全側に異常終了する（誤検知だが無言進行はしない）。
"""

import hashlib
import re
import sys
from pathlib import Path

WH = Path("wheelhouse")
by_pkg: dict[str, dict[str, list[str]]] = {}  # pkg -> {ver -> [sha, ...]}
n_whl = 0
for whl in sorted(WH.glob("*.whl")):
    m = re.match(r"([A-Za-z0-9_.]+)-([0-9][^-]*)-", whl.name)
    if not m:
        print(f"skip(命名不一致): {whl.name}", file=sys.stderr)
        continue
    n_whl += 1
    pkg, ver = m.group(1).replace("_", "-"), m.group(2)
    sha = hashlib.sha256(whl.read_bytes()).hexdigest()
    by_pkg.setdefault(pkg, {}).setdefault(ver, []).append(sha)

out = []
for pkg in sorted(by_pkg):
    vers = by_pkg[pkg]
    if len(vers) != 1:
        sys.exit(f"バージョン不一致（完全ピン違反）: {pkg} -> {sorted(vers)}")
    ver, shas = next(iter(vers.items()))
    hashes = " ".join(f"--hash=sha256:{h}" for h in sorted(set(shas)))
    out.append(f"{pkg}=={ver} {hashes}")
Path("requirements.lock").write_text("\n".join(out) + "\n", "utf-8")
print(f"requirements.lock 生成: {len(out)} packages / {n_whl} wheels")
