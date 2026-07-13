# バックエンド(FastAPI + 頭脳 + 音声認識/合成の橋渡し)をコンテナ化。
# 研究室GPUサーバなど「ターミナルで直接ライブラリを入れられない」環境でも、これ1つで動く。
#
# ビルド:  docker build -t gacha-backend .
# 実行(CPU):
#   docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... gacha-backend
# 実行(GPUでWhisperを速く):  ※ホストに nvidia-container-toolkit が要る(研究室サーバは通常あり)
#   下の GPU 用の追記を有効にしてビルド →
#   docker run --rm --gpus all -p 8000:8000 \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -e GACHA_WHISPER_DEVICE=cuda -e GACHA_WHISPER_COMPUTE=float16 -e GACHA_WHISPER_MODEL=large-v3 \
#     gacha-backend

FROM python:3.12-slim

# faster-whisper の音声デコード等の保険(webm/opus)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# GPUでWhisperを使うときは CUDA=1 でビルドすると CUDA/cuDNN を同梱する(CPUなら不要)。
# 例: docker compose -f docker-compose.yml -f docker-compose.gpu.yml build
ARG CUDA=0
RUN if [ "$CUDA" = "1" ]; then pip install --no-cache-dir nvidia-cublas-cu12 nvidia-cudnn-cu12; fi

COPY backend backend
COPY ingest ingest

EXPOSE 8000
# APIキーはイメージに焼かず、実行時に -e ANTHROPIC_API_KEY=... で渡すこと。
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
