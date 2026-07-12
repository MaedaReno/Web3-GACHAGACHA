"""音声合成(VOICEVOX)と、字幕/読み上げ用のテキスト整形。

VOICEVOX エンジン(無料。https://voicevox.hiroshiba.jp/ / Docker でも可)が
`VOICEVOX_URL`(既定 http://127.0.0.1:50021)で起動していれば、テキストを WAV 音声に
変換して返す。起動していない・失敗した場合は None を返し、呼び出し側は字幕のみに
フォールバックする(音声なしでもシステムは動く)。
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from . import config

# 絵文字などの記号(読み上げ・字幕で邪魔になる)を落とすための範囲
_EMOJI = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f000-\U0001f0ff"
    "\U00002190-\U000021ff" "\U00002b00-\U00002bff" "️" "]",
    flags=re.UNICODE,
)


def clean_text(text: str) -> str:
    """字幕・読み上げ用にテキストを整える。Markdown記号・絵文字を除去し、改行を詰める。"""
    if not text:
        return ""
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_`#>~]", "", text)      # Markdown 記号
    text = re.sub(r"\s*\n\s*", " ", text)      # 改行→空白
    text = re.sub(r"[ \t]{2,}", " ", text)     # 連続空白を1つに
    return text.strip()


def _post_json(url: str, body: bytes | None, timeout: float) -> bytes:
    req = urllib.request.Request(url, data=body or b"", method="POST")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def synthesize(
    text: str,
    speaker: int | None = None,
    base: str | None = None,
    timeout: float = 15.0,
) -> bytes | None:
    """テキスト → WAV 音声(bytes)。VOICEVOX に繋がらなければ None。"""
    if not config.TTS_ENABLED:
        return None
    text = clean_text(text)
    if not text:
        return None
    speaker = config.VOICEVOX_SPEAKER if speaker is None else speaker
    base = (base or config.VOICEVOX_URL).rstrip("/")
    try:
        # 1) 読み上げクエリを作る
        q_url = f"{base}/audio_query?speaker={speaker}&text={urllib.parse.quote(text)}"
        query = _post_json(q_url, None, timeout)
        # 2) クエリから音声を合成
        wav = _post_json(f"{base}/synthesis?speaker={speaker}", query, timeout)
        return wav
    except Exception:  # noqa: BLE001  (VOICEVOX 未起動なども含め、失敗時は音声なし)
        return None


def speakers(base: str | None = None, timeout: float = 5.0) -> list | None:
    """利用可能な話者一覧(キャラ選びの確認用)。繋がらなければ None。"""
    base = (base or config.VOICEVOX_URL).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/speakers", timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return None
