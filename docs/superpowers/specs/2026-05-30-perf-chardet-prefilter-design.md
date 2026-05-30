# 60GB 非UTF-8 コーパスの性能改善（ロックステップ共有エンジン / chardet メモ化 / rg 同梱 / prefilter 既定ON）設計

- 日付: 2026-05-30（rev.2＝批判的レビュー第1ラウンド反映）
- 正本 spec: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（§8.1/§8.2/§8.4/§9/§10.1/§10.3/§11/§15）
- 関連既存計画: `docs/superpowers/plans/2026-05-24-perf-fixedpoint-caching.md`（#1/#2/#5/#6 実装済・#3 撤回）
- 方針: **option A＝出力の TSV 行はバイト不変を厳守**した上での性能改善

> rev.2 変更点: 性能レビューで判明した「prefilter が hop×keyword 回 60GB をフルスキャンする構造的コスト（試算2.6h）」を根治するため、**全 keyword をロックステップで同時前進させ corpus 走査を共有するエンジン**を主軸に格上げ。併せて決定性(C1/H2)・並列メモ(worker ローカル)・階層キャッシュ・finalize・オフライン同梱(C-1〜C-3)・テスト観測手段の各指摘を反映。

---

## 1. 背景と根本原因（計測で確定）

60GB 規模（Java 多め・**ほとんどが非UTF-8**＝cp932/euc-jp）に対し本ツールが1日たっても完走しない。

### 1.1 ボトルネックの構造

2フェーズ: **direct**（`pipeline.py`・grep出力のファイルだけ読む・軽い）と **不動点 indirect**（`fixedpoint/__init__.py`・記号を多ホップ追跡しソース木全体を再スキャン）。`run_fixedpoint` は **毎ホップ全ファイル走査**（`use_ripgrep` 既定 False ＝ prefilter 無効）。各ファイルで `_scan_one` が「読込→`decode_bytes`→全行 automaton→（Java等）tree-sitter」を実行。

### 1.2 真の律速＝chardet（計測値）

`decode_bytes`（`encoding.py`）は UTF-8 厳格デコード失敗ファイルにだけ `chardet.detect()` を全バイトに実行。非UTF-8主体だと全ファイルが毎ホップ chardet を通る。実測（開発機）:

| 処理 | 速度 |
|---|---|
| `chardet.detect` | **約 0.1 MB/s** |
| 既知コーデックでの strict 復号 | 約 92 MB/s（**約1200倍速**） |

投影: 30GB を chardet だけで **1ホップ約108時間**。grep 行数は支配項でなく、1行入力でも数日級。

### 1.3 既存キャッシュが60GBで無力

`_FileCache`（`_scan.py`）は復号テキスト本体を予算 64MB で LRU 保持。作業集合60GB＝ヒット率約0.1%で**ホップ間再利用は実質ゼロ**。

### 1.4 過去の #3 撤回判断は本番 regime 非代表

`#3`（rg prefilter 既定ON）は「合成コーパスで実測利得ゼロ」で撤回された。だが perf コーパス `tests/perf/corpus_gen.py` は**全ファイル `"utf-8"` 生成**＝**chardet が一度も発火しない**。測っていたのは「生read＋automaton＋tree-sitter」のみで、本番（非UTF-8・chardet律速）を代表しないベンチに基づく判断。#3 の再導入は正当。

### 1.5 性能レビューで判明した第2の構造的律速（rev.2）

prefilter（rg）は**絞り込みの前に対象木をフルスキャン**する（`ripgrep.py:51-54` が `cwd=root` で `.` を走査）。現行の per-keyword 逐次・per-hop 呼び出しでは **60GB × (hop数 × keyword数)** を読む。試算 40秒/回 × 約7hop × 35keyword ≈ **2.6時間**。chardet を潰しても prefilter I/O が新たな律速になる。**「全60GBを一度デコードして索引化」はデコード＝chardet なので回避にならない**。生バイト rg が唯一 chardet を避ける手段であり、削るべきは**走査回数**＝§4 のロックステップ共有で根治する。

---

## 2. 目標と制約

- **目標**: 60GB・キーワード 30〜35 個・非UTF-8主体で **1時間以内に完走**（判定は aarch64 実機）。
- **不変条件 Inv-3**: 同一入力＋同一オプションで **keyword ごとの TSV 行はバイト不変**。診断 `diagnostics.txt` は §6 の通り一部変動を許容。
- **Inv-3 の明示前提**: **run 中ソース木は不変**（既存 `_FileCache`/finalize も同前提。メモ導入で前提が強まる）。
- **配備先**: aarch64 / Python 3.12 / **オフライン**。glibc は新しめ（公式 gnu バイナリ可）。wheelhouse の offline 再現ビルド方針を踏襲。

---

## 3. 解決策の四本柱

0. **【主軸・rev.2】全 keyword ロックステップ共有エンジン** — 35 keyword を逐次でなく同時に1段ずつ前進させ、各「グローバル hop」で全 keyword の記号和集合に対し **rg 1回＋候補デコード/走査を共有**。corpus 走査を `Σ hop_k`（≈245）から `max hop_k`（≈7）へ。
1. **encoding 検出のメモ化** — chardet を「全ファイル×全hop×全keyword」→「ユニークファイル×1回（worker 内）」へ。
2. **rg バイナリ同梱**（オフライン）＋解決経路の拡張。
3. **prefilter 既定ON 再導入**（総バイト閾値ゲート）。

運用: **`--jobs $(nproc)`** で並列化。

---

## 4. アーキテクチャとデータフロー

### 4.1 ロックステップ共有エンジン（主軸）

現行 `pipeline.run`: `for keyword: build_direct; run_fixedpoint(...)`（keyword 逐次・各々が corpus を hop 数ぶん走査）。

新構造（**ループ転置**）: `for global_hop: scan(全keywordの記号和集合); for keyword: absorb`。

```
states = { kw: ChaseState(seed_hits[kw]) for kw in 未完了keyword }   # 35状態を同時保持
global_hop = 1
while any(st.chase_active or st.terminal_active for st in states):
    # 1) 全keywordの active 記号の和集合（各stateの cap 適用後）
    union = ⋃_kw { s for s in active(states[kw]) if s not in states[kw].capped }
    if not union or global_hop > max_depth: break
    # 2) prefilter 1回（union 全体）→ 候補ファイル
    cand = prefilter(union)            # §4.4 安全条件つき
    # 3) 候補を1回だけデコード＋automaton(union)＋tree-sitter（共有）
    pass_results = scan_hop(union, cand)   # ファイル単位に (symbol,line,line,cs) を集約
    # 4) 各keywordへ pass_results を「自分の active 記号」でフィルタ吸収
    for kw in states:
        absorb_results(states[kw], pass_results, scan_chase[kw], scan_term[kw], global_hop)
    global_hop += 1
# 5) keyword ごとに indirect 構築・finalize
```

**走査回数**: グローバル hop 数（≈7）に圧縮。keyword 倍が消える。複数 keyword が同一ファイルを参照しても**デコード・パース・automaton 走査は1回**。

#### 決定性（keyword ごとの TSV 行不変）の根拠

- ある keyword の不動点結果は (seed_hits, corpus, opts, partition/chase の決定的ロジック) のみに依存。**走査を共有しても、その keyword が「自分の active 記号のヒットを、決定的にソート済みの pass_results 順で吸収する」限り、状態遷移は逐次版と同一**。`absorb_results` は既に `if symbol not in scan_chase and symbol not in scan_term: continue`（`_ingest.py:78`）で自 keyword 記号のみ拾うため、共有 pass_results を渡しても自動で正しくフィルタされる。
- **hop 番号の一致**: 逐次版で keyword K の `symbol_hop` は「K の自前 hop カウンタ」。ロックステップでは全 keyword が同時前進するので **グローバル hop g ＝ 各 active keyword の局所 hop g**。早期飽和した keyword は以降 active 記号ゼロで寄与しないだけ（逐次版でも同 hop で停止）。よって `symbol_hop` 値は逐次版と一致。
- **cap/spill/budget は per-keyword の ChaseState ローカル**（`apply_global_cap`/`maybe_spill` を各 state に対し呼ぶ）。ある keyword が cap した記号でも、別 keyword が active なら union に残り走査される（cap した keyword は吸収しないだけ）＝各 keyword 出力は逐次版と同値。
- **tree-sitter 抽出 `cs`** は (language, file, line) の純関数＝共有しても各 keyword で同値。

→ **keyword ごとの TSV 行は逐次版とバイト一致**（既存 jobs2 golden と同枠で担保）。

#### resume との整合

ロックステップ開始前に `resume.is_complete` で**完了済み keyword を除外**してから `states` を構成（逐次版の skip と同義）。

#### メモリ（トレードオフ・明記）

35 個の ChaseState（introducers/edge_store 等）を同時保持＝逐次版の約 35倍の状態常駐。`edge_store` は spill 対応。記号集合が大きい keyword が重なると常駐が増えるため、**per-keyword budget に加え、ロックステップ全体の常駐上限（state 数 × 予算）を `--memory-limit` で按分**する。本番 RAM 想定（DGX 級）と実測で確認（§9）。

### 4.2 encoding メモ（worker ローカル・rev.2 で再設計）

`abspath(str) → (enc, replaced)` の辞書。**`decode_bytes` の純粋メモ化**。

```python
def decode_with_memo(memo, abspath, raw, fallback):
    hit = memo.get(abspath)
    if hit is not None:
        enc, replaced = hit
        try:
            text = raw.decode(enc, errors="replace" if replaced else "strict")
            return text, enc, replaced
        except (LookupError, UnicodeDecodeError):
            pass                          # codec名非等価等の保険＝再計算へ降格
    text, enc, replaced = decode_bytes(raw, fallback)   # 初回のみ chardet 経路
    memo[abspath] = (enc, replaced)
    return text, enc, replaced
```

**並列の正しい持たせ方（再設計）**: 「main が集約→worker へ per-file 配布」は **Pool の引数一括生成・プロセス境界・hop毎prefilter部分集合により成立しない**（レビュー [Critical]）。代わりに **worker ローカルに enc-memo を持たせる**。Pool は run 単位で永続（`make_pool`）なので **グローバル hop をまたいで worker 内メモが効く**。`_worker_init` で空 enc-memo を生成し `_read_meta` が参照。worker 間は非共有＝最悪 jobs 倍の初回 chardet だが、**初回検出は並列で時間を稼ぐのが目的**で許容。per-file `known_enc` 引数授受は**廃止**。

**`_read_meta` は階層キャッシュ（再設計）**: ① `_FileCache.get(abspath)` hit なら即返す（text/enc 込み） ② miss なら `decode_with_memo(enc_memo, abspath, raw, fb)` で**chardet を回避**して復号 → `detect_language` → `_FileCache.put`。`_FileCache` は text 上位・enc-memo は下位フォールバック（**直交でなく階層**）。これを欠くと `_FileCache` miss（60GBでhit率0.1%）で chardet が復活し最適化が無効化する（§1.3 の再現）。

### 4.3 メモを通す経路

- **indirect 走査**: §4.2 の worker ローカル enc-memo（並列）／直列は scan_hop に enc-memo を渡す。
- **direct 走査**: `pipeline.run` の **`source` ファイル復号（`pipeline.py:90`）のみ** を memo 経由に。`cur_relpath != relpath` 分岐内（同分岐は既に連続同一ファイルを畳む）でのみ memo を読み書きし `cur_ctx` と二重化しない。**`pipeline.py:60` の `grep_enc`（`.grep` 本体の復号）は対象外**（source の enc と無関係）。
- **finalize**: `_finalize.py` の indirect hit 最終 enc 確定の再 read も memo 経由に（現状 finalize だけ chardet 残存＝「ユニーク×1回」が破れる）。

### 4.4 prefilter の安全条件（C1 根治・rev.2）

`ripgrep.py` の「除外 relpath は automaton 0 ヒット確定」は **ASCII 透過な1バイト encoding（ascii/utf-8/cp932/euc-jp/latin-1）に限り**成立。chardet が **UTF-16/UTF-32/EBCDIC 等の非ASCII透過 encoding** を返したファイルは、automaton が復号テキスト上で ASCII 記号 `Foo` をヒットさせても rg は生バイト `F\x00o\x00o` を取りこぼし、**当該ファイルが脱落して on/off で TSV 行が割れる**（Inv-3 違反）。

**対策**: prefilter のファイル**除外**を「encoding が ASCII 透過と判明したファイル」に限定。具体的には:
- memo で enc 既知かつ ASCII 透過集合に属す → rg の判定に従い除外可。
- enc 未知（初回 hop で未デコード）または **非ASCII透過と判明** → **常に走査対象に残す**（除外しない）。
- 実装: prefilter 結果 `keep_rels` に「enc 未知 or 非ASCII透過のファイル」を**無条件で和集合**して `scan_files` を作る。memo で enc が出揃う2巡目以降は除外が効く。
- §8.4 に「UTF-16/32 等 非ASCII透過 encoding は prefilter 上位集合保証外＝常に全走査」を限界として明記。回帰テストに「先頭8KB超を NUL 無し CJK で埋めた UTF-16 ファイル＋後方 ASCII 識別子」を投入。

> 補足: ASCII を含む UTF-16 は通常 `\x00` を含み `walk._is_binary`（先頭8192バイトに NUL）で skip されるが、先頭が全 CJK だと NUL 無しで通過し得るため本対策が必要。

### 4.5 rg 同梱と解決（オフライン・rev.2 で C-1〜C-3 反映）

- **配置はパッケージ内**: `src/grep_analyzer/vendor/ripgrep/{aarch64,x86_64}/rg`（ルート `vendor/` は non-editable install/wheel で消えるため不可）。`pyproject.toml` の `[tool.setuptools.package-data]` で同梱、解決は **`importlib.resources`**（`__file__` 相対は zip-safe でない）。
- **取得の供給網**: `scripts/fetch_ripgrep.py`（`gen_requirements_lock.py` と同作法＝版・URL・**期待 sha256 をスクリプト内ピン**→DL→hash 照合→配置→LICENSE 取得）。**ripgrep 14.1.1 固定**。README にオンライン再生成・オフライン再現手順。
- **起動前検証**: 同梱 rg の **sha256 を起動前照合**（`rg.sha256` 併置）。不一致は同梱を捨て which フォールバック＋診断。env `GREP_ANALYZER_RG` 指定は運用者責任で検証バイパス（信頼境界を文書化）。
- **解決の関数化**: `_resolve_rg(env, machine, which)` に切り出し**遅延評価**。順序は **env → 同梱（`machine` 正規化後）→ `shutil.which`**。`platform.machine()` 正規化辞書 `{aarch64,arm64→aarch64; x86_64,amd64,AMD64→x86_64}`、未知 arch は同梱スキップ。
- **実行可否**: 解決時に `os.access(X_OK)`→不可なら `chmod 0o755` 試行→不可なら次候補。`available()` は「解決でき・実行ビットあり・`rg --version` rc=0」のスモークまで含める（壊れ/非実行バイナリが prefilter を黙って None に落とし全走査＝目標未達に転落するのを防ぐ）。
- **`.gitattributes`**: `src/grep_analyzer/vendor/ripgrep/** -text` と binary 指定。実行ビットは fetch スクリプトが付与（git filemode 依存を避ける）。LICENSE は MIT/UNLICENSE デュアルを同梱。
- **テスト gate 統一**: `tests/conftest.py` の `requires_ripgrep` gate を `shutil.which` 直叩きから **`ripgrep.available()`（本番と同一解決順）に一本化**（配備機＝同梱rgのみで実使用経路が全 skip される死角を解消）。

### 4.6 並列の決定性

worker が返す `(enc, replaced)` は bytes の純関数。memo 状態（chardet経由か既知codec経由か）に関わらず `pass_results` は同値。**完了順・jobs 数・prefilter 有無・ロックステップ共有に非依存で keyword ごとの TSV 行不変**（Inv-3）。

---

## 5. prefilter 既定ON の閾値（golden を割らない・rev.2 で観測点明確化）

- **rg 解決可能 かつ コーパス総バイト ≥ 閾値（既定 1 GiB・`--ripgrep-threshold-bytes` で可変）** のとき既定ON。`--use-ripgrep`/`--no-use-ripgrep` で明示上書き。rg 不在は常に OFF。
- **opts の表現**: `use_ripgrep` を **tri-state（`None`=既定/閾値判定, `True`/`False`=明示）** にするか、別途 `effective_use_ripgrep` を設ける。テストはこの effective 値と「`prefilter` が呼ばれたか」を観測点にする。
- **総バイト集計（新規配線）**: `walk_files` は現状 `stat().st_size` を `max_file_bytes` 比較に使うのみで合計していない。**yield 済み（=実走査対象）ファイルの stat サイズ合計を walk 完了時に1回確定**し `collect_files` の戻り（or diag）で外へ出す。境界 `>=` 固定。走査中変動でサイズが揺れても**確定スナップショットを再評価しない**（同一入力で ON/OFF が揺れないため）。
- 効果: golden/小規模は閾値未満で OFF 据置＝diagnostics 含め完全不変、本番60GBは自動ON。

---

## 6. 出力不変の証明と診断の扱い

### 6.1 keyword ごとの TSV 行のバイト不変

- **ロックステップ共有**: §4.1 の通り、各 keyword は自 active 記号のヒットを決定的ソート順で吸収＝逐次版と状態遷移同一・hop 番号一致。→ 行不変。
- **encoding メモ**: `decode_with_memo` は `decode_bytes` の純粋メモ化（同一 bytes→同一 `(text,enc,replaced)`）。`replaced` を保存し再 decode の errors ポリシーを一致させ、`要確認` サフィックスも保存値で再現（H2）。codec 名非等価は try/except で `decode_bytes` 再計算に降格＝クラッシュ防御。
- **prefilter 既定ON**: §4.4 の安全条件（非ASCII透過/未知 enc は除外しない）により、除外されるのは「automaton 0 ヒット確定」のファイルのみ。非ASCII記号 hop は自動無効化（`ripgrep.py:41`）。→ on/off で行不変。
- **キー論拠の訂正（M3）**: 「abspath↔relpath 1:1」は realpath dedup（`walk.py:107-114`）で多:1があり厳密には誤り。正しい論拠は「**encoding は実体バイトの純関数で、どのキー設計でも同一実体には同一値**」。memo キーが abspath でも値は実体依存＝出力不変。
- **前提（M4）**: run 中ソース木不変（§2）。scan は memo・finalize は memo 経由（§4.3 で統一）＝二経路化を解消。

### 6.2 診断（diagnostics.txt）

- prefilter ON では記号を含まないファイルが走査されず、`decode_replaced`/`unsupported_shebang`/`missing_source` 等が出なくなり得る。**TSV 行のみ不変を保証**し、この差分は「影響範囲に寄与しない無関係ファイルの符号化ノイズが減るだけ」＝適切として **spec §8.4 に明記**。
- 担保: prefilter on/off で **TSV 行がバイト一致**する回帰テスト（診断対象外・golden でなく integration の TSV-only 比較）。

---

## 7. テスト方針（rev.2 で観測手段を是正）

流儀: 古典学派TDD・日本語テスト名・golden バイト一致・`requires_ripgrep`/`perf` マーカー。各 production 変更は **golden 全件バイト一致を完了条件**。

### 単体・統合（`tests/integration/`・ゲート対象）

1. `decode_with_memo` が `decode_bytes` とバイト同値（utf-8/cp932/euc-jp/latin-1＋`replaced=True`）。codec 名非等価時の再計算降格も。
2. **chardet 回数の spy は直列（jobs=1・in-process）限定**。spy 対象は `grep_analyzer.encoding.chardet.detect` 一点。同一ファイル2回目以降は呼ばれない。
3. keyword 横断共有: 複数 keyword で同一ファイルが direct/indirect に出ても chardet 1回（直列 spy）。**direct/indirect・keyword 順を変えても encoding 列が同値**（順序非依存）。
4. **並列は spy でなく配線＋バイト一致で検証**: (a) worker ローカル memo が hop 間で効く配線、(b) 出力が jobs=1 とバイト一致（既存 jobs2 golden ハーネスが担保＝新規は配線確認のみ）。
5. **ロックステップ ⇔ 逐次の keyword 別 TSV バイト一致**（新規の中核回帰）。複数 keyword・多ホップで、共有エンジン出力が「1 keyword ずつ逐次実行」と各 keyword でバイト一致。
6. rg 解決順: `_resolve_rg(env, machine, which)` を3引数注入で単体（実bin/実FS不要）。env→同梱→which、`platform.machine` 正規化、実行ビット欠落フォールバック、sha256 不一致フォールバック。`available()` のスモーク。
7. prefilter 閾値: effective 値と `prefilter` 呼出を観測。総バイト ≥ 閾値で自動ON・未満OFF・明示上書き・rg不在OFF。**`--ripgrep-threshold-bytes` 極小化で1GiB実生成不要**。総バイト集計関数は `stat` monkeypatch で単離検証。
8. **chardet 回数の決定的ロック（ゲート対象・cp932 コーパス）**: cp932 合成コーパス（全ファイル utf-8 strict 失敗かつ ASCII 記号でヒット）で **chardet 呼び出し回数 ≤ ユニークファイル数** を assert。これが「ユニーク×1回」と #3 再撤回防止の**恒久ガード**（dt でなく回数＝環境非依存）。

### 不変条件（`requires_ripgrep`）

9. prefilter on/off で TSV 行バイト一致（診断対象外・閾値ON化状態の e2e）。**C1 回帰**: 先頭 NUL 無し CJK の UTF-16 ファイル＋後方 ASCII 識別子で on/off 一致。**symlink dedup × 非UTF-8** の不変ケース。
10. golden 全件バイト一致が無傷（閾値で小規模 OFF 据置）。**golden 最大ケース総バイト < 閾値の番兵**（将来の閾値低下事故を防ぐ）。

### perf（`perf`・非ゲート＝相対比較専用）

11. cp932・**本番のファイルサイズ分布（数百行Java中心）／数GB級総量**の perf コーパスで dt/rss を print（aarch64 実機でのみ目標判定。x86_64 は相対比較）。**回帰ロックは #8（ゲート）が担う**。

---

## 8. 時間予算（1時間目標の配分・rev.2 追加）

1時間は walk＋direct＋（rgprefilter＋共有デコード＋automaton＋tree-sitter）×グローバルhop＋初回chardet の**合算**。配分目安と要対処:

| 項目 | 想定 | 対処 |
|---|---|---|
| walk（全 stat＋8KB binary read＋realpath） | 数百万ファイルで 25〜50分の恐れ | **要対処**: walk 並列化 or 既知ソース拡張子の `_is_binary` 短絡（後者は walk_skipped_binary 診断が変わるため §8.4 明記・要判断）。§9 で実測。 |
| direct フェーズ | 軽微 | memo 共有 |
| rg prefilter | 約40秒 × 約7グローバルhop ≈ 5分 | ロックステップ共有（§4.1）で keyword 倍を消去 |
| 候補デコード（初回 chardet） | 候補和集合サイズ依存・並列で按分 | memo＋jobs。**§9 実測ゲート**。未達なら option B（§10）を相談 |
| automaton＋tree-sitter | 候補×グローバルhop | lazy parse（実装済）＋共有 |

**walk コストは独立した要対処項**。ロックステップで prefilter を圧縮しても walk が 25〜50分なら目標を脅かす。§9 で最優先計測。

---

## 9. 実装範囲と承認ゲート

### 変更ファイル概略

- `src/grep_analyzer/encoding.py`: `decode_with_memo` 追加（`decode_bytes` 不変）。
- `src/grep_analyzer/fixedpoint/_scan.py`: `_read_meta` を階層キャッシュ化、`_worker_init` に worker ローカル enc-memo、`_scan_one` 接続。per-file known_enc は導入しない。
- `src/grep_analyzer/fixedpoint/__init__.py`: ロックステップ駆動（複数 ChaseState・union 走査・per-keyword 吸収）。
- `src/grep_analyzer/fixedpoint/_finalize.py`: 再 read を memo 経由に。
- `src/grep_analyzer/pipeline.py`: keyword 群の一括 seed・ロックステップ呼び出し・direct 経路 memo・resume 除外。
- `src/grep_analyzer/ripgrep.py`: `_resolve_rg` 関数化、env→同梱→which、machine 正規化、sha256/exec スモーク、安全条件（非ASCII透過/未知は除外しない）。
- `src/grep_analyzer/walk.py`: 総バイト集計の確定スナップショット出力。（walk 高速化は §8 の判断次第）
- `src/grep_analyzer/cli.py`: prefilter tri-state＋閾値＋`--ripgrep-threshold-bytes`。
- `src/grep_analyzer/vendor/ripgrep/{aarch64,x86_64}/rg`＋`rg.sha256`＋`LICENSE`、`scripts/fetch_ripgrep.py`、`pyproject.toml` package-data、`.gitattributes`。
- `tests/conftest.py`: gate を `ripgrep.available()` に統一。
- `tests/integration/`・`tests/perf/`・golden（小規模不変・新規ケースのみ）。
- spec §8.4 注記。

### 承認ゲート（§9 計測を gate 化）

実装着手前ではなく、**実装後の最初の検証として**:
1. walk 単体時間（最優先）。
2. cp932・本番サイズ分布の perf コーパスで chardet 総コスト・rg 走査総量・RAM ピークを実測。
3. aarch64 実機で 1時間目標の合否判定。未達なら §10 のいずれかを相談。

---

## 10. スコープ外・コンティンジェンシー

option A（出力不変）を維持。§9 ゲートで未達の場合に相談する次レバー:

- (a) **encoding メモのディスク永続化**（再実行で chardet ゼロ・mtime/size キーで無効化）。
- (b) **chardet 撤去/差替**（既知環境前提で cp932/euc-jp strict 先行試行 or 先頭サンプル検出 or cchardet）。**出力ベースライン更新＝spec 改定とレビュー前提**＝option B。性能レビューは「初回 chardet が主レバー」と指摘しており、§9 未達時の最有力。
- (c) **walk の並列化/拡張子短絡**（§8）。

---

## 付録: 批判的レビュー第1ラウンドの反映状況

| 指摘 | 重大度 | 反映 |
|---|---|---|
| C1 prefilter の ASCII 上位集合が UTF-16 等で破れる | Critical | §4.4 安全条件・§9 回帰テスト |
| 並列 per-file known_enc 授受が成立しない | Critical | §4.2 worker ローカル memo に再設計 |
| `_read_meta` の階層キャッシュ未設計で chardet 復活 | Critical | §4.2 階層明文化 |
| prefilter ×hop×keyword フルスキャン 2.6h | High | §4.1 ロックステップ共有 |
| vendor がパッケージ外で install 後に消える | Critical | §4.5 パッケージ内＋package-data |
| conftest gate と本番解決の乖離 | Critical | §4.5 `available()` 統一 |
| バイナリ供給網が wheelhouse 水準未達 | Critical | §4.5 fetch スクリプト＋sha256 |
| H2 並列で `replaced` 取りこぼし | High | §4.2 `(enc,replaced)` 対 |
| finalize の chardet 残存 | 重要 | §4.3 memo 経由 |
| chardet spy が別プロセスで効かない | Critical(test) | §7-2/4 直列限定＋配線検証 |
| perf 非ゲートで再発防御にならない | Critical(test) | §7-8 ゲート assert に分離 |
| 閾値の opts 表現・総バイト配線未定義 | High(test) | §5 tri-state＋確定スナップショット |
| 初回 chardet が主レバー・§9 をゲート化 | High | §8 時間予算・§9 ゲート・§10(b) |
| walk 25〜50分 | Medium | §8 要対処項 |
| platform.machine 正規化/exec ビット/sha256 | High | §4.5 |
| M3/M4/M5 論拠・前提・閾値境界 | Medium | §6.1/§2/§5 |
