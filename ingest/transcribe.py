"""講義動画の文字起こし(Phase 0)。

YouTube 等の URL(または手元の動画/音声ファイル)を faster-whisper でタイムスタンプ付き
テキストに変換し、1本につき 1 つの JSON を `ingest/data/lectures/` に書き出す。

出力フォーマット(セグメント単位。チャンク分割は build_index.py が行う):
    [{"id", "lecture", "timestamp", "text", "start", "end"}, ...]

使い方:
    # YouTube URL(タイトルを講義名に使う)
    python ingest/transcribe.py "https://youtu.be/xxxx"
    # 講義名を明示 + 手元の動画
    python ingest/transcribe.py --lecture "第1回" ~/lectures/lec1.mp4
    # 複数まとめて(URL とローカルファイルの混在可)
    python ingest/transcribe.py url1 url2 ./lec3.mp4

依存: faster-whisper、および YouTube DL 時のみ yt-dlp。
モデルは環境変数で調整(既定は config の GACHA_WHISPER_*):
    GACHA_WHISPER_MODEL=large-v3 GACHA_WHISPER_DEVICE=cuda GACHA_WHISPER_COMPUTE=float16
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import config  # noqa: E402


def _fmt_ts(seconds: float) -> str:
    """秒 → mm:ss(1時間超は hh:mm:ss)。出典表示用。"""
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _slug(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"[^\w\-぀-ヿ一-鿿]", "", text)
    return text[:60] or "lecture"


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _download_audio(url: str, dest_dir: str) -> tuple[str, str]:
    """URL の音声を dest_dir に落とし、(音声ファイルパス, 動画タイトル) を返す。"""
    try:
        import yt_dlp  # 遅延インポート
    except ImportError:
        sys.exit(
            "yt-dlp が未導入です。`pip install yt-dlp` するか、"
            "手元の動画ファイルを引数に渡してください。"
        )
    outtmpl = os.path.join(dest_dir, "%(id)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        title = info.get("title") or info.get("id") or url
    return path, title


def _load_whisper():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper が未導入です。`pip install faster-whisper` してください。")
    return WhisperModel(
        config.WHISPER_MODEL,
        device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE,
    )


def transcribe_one(source: str, model, lecture: str | None, out_dir: str, tmp_dir: str) -> str:
    """1本を文字起こしして JSON を書き出し、出力パスを返す。"""
    if _is_url(source):
        print(f"  ダウンロード中: {source}")
        audio_path, title = _download_audio(source, tmp_dir)
        lecture_name = lecture or title
    else:
        if not os.path.exists(source):
            sys.exit(f"ファイルが見つかりません: {source}")
        audio_path = source
        lecture_name = lecture or os.path.splitext(os.path.basename(source))[0]

    print(f"  文字起こし中(model={config.WHISPER_MODEL}, device={config.WHISPER_DEVICE}) …")
    segments, _info = model.transcribe(audio_path, language="ja")

    slug = _slug(lecture_name)
    rows = []
    for i, seg in enumerate(segments):
        text = (seg.text or "").strip()
        if not text:
            continue
        rows.append({
            "id": f"{slug}-{i:04d}",
            "lecture": lecture_name,
            "timestamp": _fmt_ts(seg.start),
            "text": text,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
        })

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{slug}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"  → {out_path}({len(rows)} セグメント)")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="講義動画/URL を文字起こしする")
    ap.add_argument("sources", nargs="+", help="YouTube URL または動画/音声ファイルパス")
    ap.add_argument("--lecture", help="講義名(出典表示に使う。単体指定時のみ有効)")
    ap.add_argument(
        "--out-dir",
        default=os.path.join(config.INGEST_DATA_DIR, "lectures"),
        help="出力ディレクトリ",
    )
    args = ap.parse_args()

    if args.lecture and len(args.sources) > 1:
        print("※ --lecture は複数指定時は無視されます(各動画のタイトルを使用)。")
        args.lecture = None

    model = _load_whisper()
    with tempfile.TemporaryDirectory(prefix="gacha-transcribe-") as tmp:
        for src in args.sources:
            print(f"[{src}]")
            transcribe_one(src, model, args.lecture, args.out_dir, tmp)

    print(
        "\n完了。次は `python ingest/build_index.py` でインデックスを構築してください。"
    )


if __name__ == "__main__":
    main()
