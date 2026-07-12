"""音声認識(faster-whisper / STT)。

ブラウザで録音した音声(webm/opus など)のバイト列を受け取り、日本語で文字起こしする。
モデルは初回に一度だけ読み込む(以降は使い回し)。faster-whisper 未導入や失敗時は
None を返し、呼び出し側は「聞き取れなかった」旨をユーザーに伝える(落ちない)。

依存: faster-whisper(重い)。開発は CPU + small で可、本番の高速化は GPU 推奨。
"""

from __future__ import annotations

import io

from . import config

_model = None
_load_failed = False


def _get_model():
    """WhisperModel を遅延ロード(未導入でもモジュール import は通る)。失敗時は None。"""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )
        return _model
    except Exception:  # noqa: BLE001  (未導入・モデルDL失敗・GPU未設定など)
        _load_failed = True
        return None


def transcribe(audio_bytes: bytes, language: str = "ja") -> str | None:
    """音声バイト列 → 認識テキスト。無効/失敗時は None。"""
    if not config.STT_ENABLED or not audio_bytes:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        # faster-whisper は BytesIO を受け取り、内部(PyAV)で opus/webm 等をデコードする
        segments, _info = model.transcribe(io.BytesIO(audio_bytes), language=language)
        text = "".join(seg.text for seg in segments).strip()
        return text or None
    except Exception:  # noqa: BLE001
        return None
