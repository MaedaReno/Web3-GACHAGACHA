"""講義資料(PDF)の取り込み(Phase 0)。

`ingest/data/materials/` に置いた PDF からテキストを抽出し、講義動画・Discord と同じ経路で
インデックス化できる形にまとめて `ingest/data/materials.json` に書き出す。

出力フォーマット(build_index.py が読む形):
    [{"id", "lecture", "timestamp", "text"}, ...]
  - lecture: PDF のファイル名(拡張子なし)。出典表示に出るので「第3回資料」等の名前を推奨。
  - timestamp: "p.5" のようにページ番号(出典の位置に流用)。

使い方:
    # ingest/data/materials/ に PDF を置いてから
    python ingest/materials_parse.py
    # ファイル/フォルダを明示することも可
    python ingest/materials_parse.py slides/第3回.pdf

注意: 画像スキャンだけの PDF はテキストが取れない(0件)。その場合は OCR が別途必要。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config  # noqa: E402

CHUNK_CHARS = 320  # 検索粒度(講義動画のチャンクと揃える)


def _clean(text: str) -> str:
    """抽出テキストの余分な空白・改行を整理する。"""
    text = re.sub(r"[ \t]+", " ", text or "")
    return re.sub(r"\n{2,}", "\n", text).strip()


def _rows_from_pages(stem: str, pages: list[tuple[int, str]]) -> list[dict]:
    """(ページ番号, 本文) の列 → チャンク化した行。PDF に依存しない純粋関数(テスト可)。"""
    rows: list[dict] = []
    n = 0
    for pno, raw in pages:
        text = _clean(raw)
        if not text:
            continue
        # ページ本文を CHUNK_CHARS ごとに分割(スライドは短いので大抵1ページ1チャンク)
        for i in range(0, len(text), CHUNK_CHARS):
            piece = text[i : i + CHUNK_CHARS].strip()
            if not piece:
                continue
            rows.append({
                "id": f"mat-{stem}-p{pno}-{n:04d}",
                "lecture": stem,
                "timestamp": f"p.{pno}",
                "text": piece,
            })
            n += 1
    return rows


def _pdf_rows(path: str) -> list[dict]:
    try:
        from pypdf import PdfReader  # 遅延インポート
    except ImportError:
        sys.exit("pypdf が未導入です。`pip install pypdf` してください。")

    reader = PdfReader(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    pages = [(pno, page.extract_text() or "") for pno, page in enumerate(reader.pages, start=1)]
    return _rows_from_pages(stem, pages)


def main() -> None:
    default_dir = os.path.join(config.INGEST_DATA_DIR, "materials")
    ap = argparse.ArgumentParser(description="講義資料(PDF)からテキストを抽出して取り込む")
    ap.add_argument(
        "paths",
        nargs="*",
        help=f"PDF ファイル/フォルダ。省略時は {default_dir}/*.pdf を処理",
    )
    ap.add_argument(
        "--out",
        default=os.path.join(config.INGEST_DATA_DIR, "materials.json"),
        help="出力ファイル",
    )
    args = ap.parse_args()

    # 引数がフォルダなら中の PDF を、ファイルならそのまま、無指定なら既定フォルダを対象に
    pdfs: list[str] = []
    targets = args.paths or [default_dir]
    for t in targets:
        if os.path.isdir(t):
            pdfs.extend(sorted(glob.glob(os.path.join(t, "*.pdf"))))
        elif os.path.isfile(t):
            pdfs.append(t)
        else:
            print(f"※ 見つかりません: {t}")
    if not pdfs:
        sys.exit(
            f"PDF が見つかりません。{default_dir}/ に置くか、引数で指定してください。"
        )

    all_rows: list[dict] = []
    for path in pdfs:
        rows = _pdf_rows(path)
        if not rows:
            print(f"[{os.path.basename(path)}] 0 件 ⚠ テキストが取れません(画像PDF?→要OCR)")
        else:
            print(f"[{os.path.basename(path)}] {len(rows)} チャンク")
        all_rows.extend(rows)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
    print(f"→ {args.out}(合計 {len(all_rows)} チャンク)")
    print("次は `python ingest/build_index.py` でインデックスを再構築してください。")


if __name__ == "__main__":
    main()
