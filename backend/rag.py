"""講義・Discord知識の検索(RAG)。

Phase 1 では暫定として、サンプルコーパス上の素朴なキーワードスコアリングで動かす。
Phase 0 で本格RAG(bge-m3 埋め込み + Qdrant ハイブリッド検索)に差し替える際は、
この `search()` の中身だけを置き換えればよい(戻り値の形は維持する)。
"""

from __future__ import annotations

import json
import re

from . import config


def _load_corpus(path: str | None = None) -> list[dict]:
    path = path or config.LECTURE_CORPUS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Retriever:
    def __init__(self, corpus: list[dict] | None = None):
        self.corpus = corpus if corpus is not None else _load_corpus()

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """クエリに関連する講義断片を返す。

        戻り値: [{lecture, timestamp, text, score}, ...]
        (本格RAG化後もこの形を維持すること)
        """
        terms = [t for t in re.split(r"\s+", (query or "").strip().lower()) if t]
        scored = []
        for doc in self.corpus:
            text = doc["text"].lower()
            # 素朴なスコア: 語の含有数 + 部分一致
            score = sum(text.count(t) for t in terms) if terms else 0
            if score == 0 and query and query.strip():
                # 語分割で拾えない日本語向けに、クエリ全体の部分一致も見る
                if query.strip().lower() in text:
                    score = 1
            if score > 0:
                scored.append({**doc, "score": score})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]
