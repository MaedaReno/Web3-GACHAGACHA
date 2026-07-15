"""インデックス構築(Phase 0)。

transcribe.py / discord_parse.py が出力した中間 JSON を読み、チャンク分割して
bge-m3 で埋め込み、Qdrant コレクションに投入する。以降 backend/rag.py が自動的に
このコレクションを使う(URL 未指定なら埋め込みモードで同じ path を読む)。

  入力: {INGEST_DATA}/lectures/*.json(セグメント)、{INGEST_DATA}/discord.json(任意)
  出力: Qdrant コレクション config.QDRANT_COLLECTION(既定 "lectures")

使い方:
    python ingest/build_index.py            # 既存コレクションを作り直して投入
    python ingest/build_index.py --dry-run  # チャンク数だけ確認(埋め込み・投入なし)

注意: 埋め込みモード(URL未指定)は path を排他ロックするため、バックエンドを
起動したままだと失敗する。ビルド中はサーバを止めておくこと。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config  # noqa: E402

CHUNK_CHARS = 320  # 講義セグメントを結合する目安の文字数


def _chunk_lecture_file(path: str) -> list[dict]:
    """セグメント列を連続結合して ~CHUNK_CHARS のチャンクにまとめる。"""
    with open(path, encoding="utf-8") as f:
        segs = json.load(f)
    chunks, buf, n = [], [], 0
    for seg in segs:
        buf.append(seg)
        if sum(len(s["text"]) for s in buf) >= CHUNK_CHARS:
            chunks.append(_merge(buf, path, n)); n += 1; buf = []
    if buf:
        chunks.append(_merge(buf, path, n))
    return chunks


def _merge(segs: list[dict], path: str, n: int) -> dict:
    head = segs[0]
    slug = os.path.splitext(os.path.basename(path))[0]
    return {
        "id": f"{slug}-c{n:03d}",
        "lecture": head["lecture"],
        "timestamp": head["timestamp"],       # チャンク先頭の時刻を出典に
        "text": "".join(s["text"] for s in segs),
    }


def _load_discord() -> list[dict]:
    path = os.path.join(config.INGEST_DATA_DIR, "discord.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    # message 単位でそのまま 1 チャンク(author は payload には含めず text 先頭に添える)
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "lecture": r["lecture"],
            "timestamp": r.get("timestamp", ""),
            "text": (f"{r['author']}: " if r.get("author") else "") + r["text"],
        })
    return out


def collect_chunks() -> list[dict]:
    chunks: list[dict] = []
    lec_dir = os.path.join(config.INGEST_DATA_DIR, "lectures")
    for path in sorted(glob.glob(os.path.join(lec_dir, "*.json"))):
        c = _chunk_lecture_file(path)
        print(f"[講義] {os.path.basename(path)} → {len(c)} チャンク")
        chunks.extend(c)
    disc = _load_discord()
    if disc:
        print(f"[Discord] {len(disc)} チャンク")
    chunks.extend(disc)
    return chunks


def build(dry_run: bool = False) -> None:
    chunks = collect_chunks()
    if not chunks:
        sys.exit(
            "投入対象がありません。先に transcribe.py / discord_parse.py を実行してください。"
        )
    print(f"合計 {len(chunks)} チャンク")
    if dry_run:
        print("--dry-run のため埋め込み・投入はスキップしました。")
        return

    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from backend.embeddings import embed_texts

    print("埋め込み中(bge-m3)…")
    vectors = embed_texts([c["text"] for c in chunks])

    if config.QDRANT_URL:
        client = QdrantClient(url=config.QDRANT_URL)
    else:
        os.makedirs(config.QDRANT_PATH, exist_ok=True)
        client = QdrantClient(path=config.QDRANT_PATH)

    # 作り直し(冪等: 何度流しても同じ状態になる)
    if client.collection_exists(config.QDRANT_COLLECTION):
        client.delete_collection(config.QDRANT_COLLECTION)
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=VectorParams(size=config.EMBED_DIM, distance=Distance.COSINE),
    )
    points = [
        PointStruct(id=i, vector=vectors[i], payload=chunks[i])
        for i in range(len(chunks))
    ]
    client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)
    print(
        f"→ Qdrant コレクション '{config.QDRANT_COLLECTION}' に {len(points)} 件投入完了"
        f"({'URL:'+config.QDRANT_URL if config.QDRANT_URL else 'path:'+config.QDRANT_PATH})"
    )
    print("バックエンドを起動すれば rag.py が自動でこのインデックスを使います。")


def main() -> None:
    ap = argparse.ArgumentParser(description="チャンク分割+bge-m3埋め込み→Qdrant投入")
    ap.add_argument("--dry-run", action="store_true", help="チャンク数のみ確認")
    args = ap.parse_args()
    build(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
