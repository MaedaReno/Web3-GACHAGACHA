"""講義・Discord知識の検索(RAG)。

本番は bge-m3 埋め込み + Qdrant のベクトル検索。Qdrant/埋め込みモデルが使えない
環境(依存未導入・インデックス未構築など)では、サンプルコーパス上の素朴なキーワード
方式へ自動フォールバックする。どちらの経路でも `search()` の戻り値の形は同じ:

    [{"id", "lecture", "timestamp", "text", "score"}, ...]

Phase 0 で `ingest/build_index.py` を流すと Qdrant コレクションが埋まり、以降は
自動的にベクトル検索が使われる(呼び出し側=llm.py / cli.py の変更は不要)。
"""

from __future__ import annotations

import json
import re

from . import config


def _load_corpus(path: str | None = None) -> list[dict]:
    path = path or config.LECTURE_CORPUS_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class _QdrantBackend:
    """bge-m3 + Qdrant によるベクトル検索。使えないときは __init__ で例外を投げる。"""

    def __init__(self):
        from qdrant_client import QdrantClient  # 遅延インポート

        if config.QDRANT_URL:
            self.client = QdrantClient(url=config.QDRANT_URL)
        else:
            # 埋め込みモード(ローカル永続・Docker不要)
            self.client = QdrantClient(path=config.QDRANT_PATH)

        self.collection = config.QDRANT_COLLECTION
        # コレクションが存在し、点が入っているかを確認(空なら使わない)
        if not self.client.collection_exists(self.collection):
            raise RuntimeError(f"Qdrant collection '{self.collection}' が無い")
        count = self.client.count(self.collection, exact=True).count
        if count == 0:
            raise RuntimeError(f"Qdrant collection '{self.collection}' が空")

    def search(self, query: str, top_k: int) -> list[dict]:
        from .embeddings import embed_query

        vec = embed_query(query)
        res = self.client.query_points(
            collection_name=self.collection,
            query=vec,
            limit=top_k,
            with_payload=True,
        )
        hits = []
        for p in res.points:
            payload = p.payload or {}
            hits.append({
                "id": payload.get("id", str(p.id)),
                "lecture": payload.get("lecture", ""),
                "timestamp": payload.get("timestamp", ""),
                "text": payload.get("text", ""),
                "score": round(float(p.score), 4),
            })
        return hits


class Retriever:
    """講義知識の検索窓口。Qdrant が使えればベクトル検索、無理ならキーワード方式。"""

    def __init__(self, corpus: list[dict] | None = None):
        # 明示的にコーパスを渡された場合(テスト等)はキーワード方式に固定する。
        self._forced_keyword = corpus is not None
        self._corpus = corpus
        self._backend = None
        if not self._forced_keyword:
            try:
                self._backend = _QdrantBackend()
            except Exception:
                # 依存未導入・未構築・ロック中など。キーワード方式に落ちる。
                self._backend = None

    @property
    def backend_name(self) -> str:
        return "qdrant" if self._backend is not None else "keyword"

    def _keyword_corpus(self) -> list[dict]:
        if self._corpus is None:
            self._corpus = _load_corpus()
        return self._corpus

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        terms = [t for t in re.split(r"\s+", (query or "").strip().lower()) if t]
        scored = []
        for doc in self._keyword_corpus():
            text = doc["text"].lower()
            score = sum(text.count(t) for t in terms) if terms else 0
            if score == 0 and query and query.strip():
                if query.strip().lower() in text:
                    score = 1
            if score > 0:
                scored.append({**doc, "score": score})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """クエリに関連する講義断片を返す。

        戻り値: [{id, lecture, timestamp, text, score}, ...]
        """
        if self._backend is not None:
            try:
                return self._backend.search(query, top_k)
            except Exception:
                # 実行時に Qdrant が落ちても会話は止めない(キーワードで継続)。
                pass
        return self._keyword_search(query, top_k)
