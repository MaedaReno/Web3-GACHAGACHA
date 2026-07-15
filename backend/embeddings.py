"""bge-m3 埋め込み(ローカル・無料)。build_index.py と rag.py で共有する。

FlagEmbedding の BGEM3FlagModel を遅延ロードするシングルトン。SDK 未導入の環境では
import 時ではなく最初の encode 時に ImportError を出す(rag.py 側がそれを捕まえて
キーワード方式へフォールバックできるように)。
"""

from __future__ import annotations

from . import config

_model = None


def _get_model():
    """bge-m3 モデルを一度だけロードして使い回す。"""
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel  # 遅延インポート(重い)

        _model = BGEM3FlagModel(config.EMBED_MODEL, use_fp16=config.EMBED_USE_FP16)
    return _model


def _encode(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    out = model.encode(texts, batch_size=16, max_length=1024)
    vecs = out["dense_vecs"]
    # numpy 配列 → プレーンな list(Qdrant へそのまま渡せる形)
    return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vecs]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """複数テキストを埋め込む(インデックス構築用)。"""
    if not texts:
        return []
    return _encode(texts)


def embed_query(text: str) -> list[float]:
    """1件のクエリを埋め込む(検索用)。"""
    return _encode([text])[0]
