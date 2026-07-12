"""集中設定。値切り・クイズ・報酬・モデルなどのパラメータをここで一元管理する。

金額の単位は「講義内仮想通貨のトークン」。実運用の受取アドレスやチェーン設定は
決済連携(Phase 4)で payment.py に追加する。
"""

import os

# --- LLM(頭脳) ---
# 既定は claude-haiku-4-5(最も安い。開発・デモ向け)。
# 本番でもう少し賢さが欲しければ claude-sonnet-5 に切り替える(Opus は使わない方針)。
#   例: GACHA_MODEL=claude-sonnet-5 で起動
MODEL = os.environ.get("GACHA_MODEL", "claude-haiku-4-5")

# effort は Haiku 4.5 / Sonnet 4.5 では非対応(送るとエラー)。対応モデルのときだけ送る。
_NO_EFFORT_MODELS = {"claude-haiku-4-5", "claude-sonnet-4-5"}
SUPPORTS_EFFORT = MODEL not in _NO_EFFORT_MODELS
EFFORT = os.environ.get("GACHA_EFFORT", "low")  # low | medium | high | max(対応モデルのみ)

MAX_TOKENS = 1024

# --- 価格(サーバ側で厳格に管理する。LLMには床値を渡さない) ---
LIST_PRICE = 300          # 定価(交渉の出発点)
BASE_FLOOR_PRICE = 200    # 通常の下限(値切りだけではここまで)
ABSOLUTE_MIN_PRICE = 100  # クイズ報酬を積んでも絶対に割らない最低額

# --- クイズ報酬 ---
# 正解1問ごとに実質下限をこの額だけ引き下げる(=「いいことが起こる」)。
QUIZ_DISCOUNT_PER_CORRECT = 50
MAX_QUIZ_QUESTIONS = 3    # 1取引で出題できる上限

# --- Phase 3: 音声合成(VOICEVOX) ---
# VOICEVOX エンジン(無料アプリ / Docker)を起動しておくと、店長の返事を音声化して
# モニター(ステージ)で再生する。起動していなければ自動で字幕のみにフォールバックする。
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
VOICEVOX_SPEAKER = int(os.environ.get("VOICEVOX_SPEAKER", "3"))  # 例: 3=ずんだもん(ノーマル)
TTS_ENABLED = os.environ.get("GACHA_TTS", "1") != "0"           # 0 で音声合成を無効化

# --- Phase 3: 音声認識(faster-whisper / STT) ---
# 開発(CPU)は small + int8 が無難。研究室GPUなら large-v3 + cuda + float16 が高精度・高速。
STT_ENABLED = os.environ.get("GACHA_STT", "1") != "0"
WHISPER_MODEL = os.environ.get("GACHA_WHISPER_MODEL", "small")   # tiny/base/small/medium/large-v3
WHISPER_DEVICE = os.environ.get("GACHA_WHISPER_DEVICE", "auto")  # auto | cpu | cuda
WHISPER_COMPUTE = os.environ.get("GACHA_WHISPER_COMPUTE", "int8")  # int8(CPU) | float16(GPU)

# --- Phase 4: 決済(Optimism / ICHIGO ERC-20)と解錠 ---
# ICHIGO_game(既存決済サイト)と同じ設定。★テスト中は受取先を自分のアドレスにすると
# トークンが戻り、ガス代だけで何度も検証できる(フロントの NEXT_PUBLIC_GACHA_WALLET も合わせる)。
OPTIMISM_RPC = os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io")
ICHIGO_TOKEN_ADDR = os.environ.get(
    "ICHIGO_TOKEN_ADDR", "0x836700463Dce76D9Cc3CDf6F6EDF946312c01869"
)
GACHA_WALLET = os.environ.get(
    "GACHA_WALLET", "0x0d9Ff88703b8bcB42ca7e526246C2dcf9A4aEdb9"
)  # 受取(集約)先
TOKEN_DECIMALS = int(os.environ.get("ICHIGO_DECIMALS", "18"))

# ESP32 と共有する合言葉。/gacha/poll?token=... で照合する。★本番では必ず変更。
UNLOCK_TOKEN = os.environ.get("GACHA_UNLOCK_TOKEN", "change-me-secret")

# --- データファイル ---
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
QUIZ_BANK_PATH = os.environ.get(
    "GACHA_QUIZ_BANK", os.path.join(_ROOT, "ingest", "quiz_bank.json")
)
# Phase 0 の本格RAG(Qdrant)導入までの暫定コーパス。
LECTURE_CORPUS_PATH = os.environ.get(
    "GACHA_LECTURE_CORPUS", os.path.join(_ROOT, "ingest", "lectures_sample.json")
)
