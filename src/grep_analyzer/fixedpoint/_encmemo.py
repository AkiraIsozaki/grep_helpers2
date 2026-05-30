"""worker ローカル enc-only メモ（LRU 件数予算）。値は (enc, replaced) の小タプル。"""
from collections import OrderedDict

_DEFAULT_MAX = 2_000_000        # 数百万ファイルを概ね収容しつつ常駐を有界化


class EncMemo:
    """abspath -> (enc, replaced) の LRU 件数予算メモ。

    decode_with_memo が memo.get / memo[k]= で使えるよう dict 互換の
    get/__getitem__/__setitem__/__contains__ を実装する。
    """

    def __init__(self, max_entries: int = _DEFAULT_MAX):
        self.max = max_entries
        self._d: "OrderedDict[str, tuple]" = OrderedDict()

    def get(self, key, default=None):
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v if v is not None else default

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        v = self._d[key]
        self._d.move_to_end(key)
        return v

    def __setitem__(self, key, value):
        if key in self._d:
            del self._d[key]
        self._d[key] = value
        while len(self._d) > self.max:
            self._d.popitem(last=False)
