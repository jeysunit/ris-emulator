# syntax=docker/dockerfile:1
# ris-emulator のイメージ（Web 画面と MWL の SCP を1つのプロセスで動かす）。
#
# - ベースイメージは Python の公式イメージ（slim）。試験用のパッケージは入れない
# - root 以外のユーザー（ris、uid 10001）で動かす。コードの所有者は root のまま（ris は読み取りだけ）
# - 設定は外から /app/config/app_config.yaml に mount できる（イメージの中の設定は例）
# - 待ち受けのアドレスは環境変数 RIS_WEB_BIND_ADDRESS・RIS_MWL_BIND_ADDRESS で 0.0.0.0 にしてある
#   （設定ファイルの bind_address より先に効く）。HTTP Basic のパスワードのファイルを
#   RIS_WEB_PASSWORD_FILE で渡す（README の「Docker で動かす」）
# - 書き込む場所：/app/state（予約の SQLite）

# ベースイメージは digest で固定する（dicom-test-generator の Dockerfile と同じイメージ。
# マルチアーキテクチャの manifest list の digest）。更新するときは docker buildx imagetools inspect で確かめる
ARG PYTHON_IMAGE=python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RIS_WEB_BIND_ADDRESS=0.0.0.0 \
    RIS_MWL_BIND_ADDRESS=0.0.0.0

WORKDIR /app

# 依存は requirements.txt から入れる。試験（pytest・httpx）の行だけを外す
COPY requirements.txt ./
RUN grep -viE '^(pytest|httpx)([<>=!~ ;#]|$)' requirements.txt > /tmp/requirements-runtime.txt \
  && pip install -r /tmp/requirements-runtime.txt \
  && rm /tmp/requirements-runtime.txt \
  && pip list --format=freeze

COPY app ./app
COPY config ./config
COPY data ./data

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin ris \
  && mkdir -p state \
  && chown ris:ris state

USER 10001

# 8081: Web 画面、11112: MWL（DICOM）
EXPOSE 8081 11112

CMD ["python", "-m", "app.web"]
