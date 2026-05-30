"""不動点・ターゲットスキャン・エンジン。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain を
出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
来歴エッジは introducers（実抽出元 Occurrence 群）ベース＝§8.2 を精密化(偽 chain 根治)。
出力は走査順・並列完了順に非依存で決定的(§9)。

停止性(§8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用集合
単調増加(state.chase_done から削らない＝cap は state.capped で scan 除外のみ)。よって高々
|母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。

Related: spec §8.1, §8.2, §8.3, §8.4, §9
"""

from pathlib import Path

from grep_analyzer import walk
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._encmemo import EncMemo
from grep_analyzer.fixedpoint._lockstep import run_fixedpoint_multi
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import make_pool
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit

__all__ = ["EngineOptions", "make_pool", "run_fixedpoint", "run_fixedpoint_multi"]


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None, unsafe_rels=None, enc_memo=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (relpath, abspath) 列を使う（同値）。

    unsafe_rels は非ASCII透過（UTF-16/32 BOM 等）ファイルの relpath 集合で、prefilter
    ON 時も常に走査対象に残す（rg は生バイトの ASCII symbol を見つけられず脱落させるため）。
    NOTE(rev.2 H2): files=None（内部 walk フォールバック）の場合は unsafe_rels 保護を
    適用しない＝この経路は直接呼ぶテスト向け。本番 pipeline は常に files と unsafe_rels の
    両方を渡す。
    """
    if files is None and unsafe_rels:
        raise ValueError(
            "unsafe_rels は files と併用必須（files=None の walk フォールバックは unsafe 救済を適用しない）")
    source_root = Path(source_root)
    if enc_memo is None:
        enc_memo = EncMemo()                  # 後方互換の内部既定（run 共有 enc-memo）
    # seed 初期化の復号も run 共有 enc-memo を通し、同一ファイルの再 chardet を抑止する
    # （direct/scan/finalize と単一情報源を共有）。
    state = initialize_state(seed_hits, source_root, opts, diag, enc_memo=enc_memo)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))

    # ループは lock-step 共有エンジンへ委譲（rev.2 C-3）。単一 keyword は byte 同値。
    # state.rel_to_abs / state.enc_memo / Progress / automaton_split は
    # run_fixedpoint_multi 側で駆動する（二重駆動しない）。
    result = run_fixedpoint_multi(
        {state.keyword: state}, source_root, opts,
        files=files, unsafe_rels=unsafe_rels, enc_memo=enc_memo)
    return result[state.keyword]
