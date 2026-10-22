"""設定ファイル（config/app_config.yaml）の読み込み（docs/spec/03_web_cli.md 4 章）.

相対のパスは、プロセスの作業ディレクトリから辿る。
環境変数 `RIS_WEB_BIND_ADDRESS`・`RIS_MWL_BIND_ADDRESS` があれば、待ち受けのアドレスを上書きする。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import ConfigurationError
from app.core.models import (
    LO_MAX_LENGTH,
    SH_MAX_LENGTH,
    CharacterSet,
    OrderStatus,
    Procedure,
    has_control_chars,
    is_final,
    validate_ae_title,
)

PORT_MIN = 1
PORT_MAX = 65535
DEFAULT_MAX_RESULTS = 1000
MAX_RESULTS_LIMIT = 100_000
ACCESSION_PREFIX_MAX_LENGTH = 4
PATIENT_ID_PREFIX_MAX_LENGTH = 8
ISSUER_PATTERN = re.compile(r"[A-Za-z0-9_]{1,16}")
WEB_BIND_ENV = "RIS_WEB_BIND_ADDRESS"
MWL_BIND_ENV = "RIS_MWL_BIND_ADDRESS"
RetakeMode = Literal["append", "new_order"]


class MwlConfig(BaseModel):
    model_config = {"frozen": True}

    ae_title: str = "RIS_EMU"
    bind_address: str = "127.0.0.1"
    port: int = Field(11112, ge=PORT_MIN, le=PORT_MAX)
    # MWL で返す予約の状態。完了・取消は既定で返さない
    statuses: list[OrderStatus] = Field(
        default_factory=lambda: [OrderStatus.SCHEDULED, OrderStatus.IN_PROGRESS]
    )
    # 一致した件数がこれを超えたら、返さずに A700（Out of resources）で断る
    max_results: int = Field(DEFAULT_MAX_RESULTS, ge=1, le=MAX_RESULTS_LIMIT)
    # 相手の Called AE Title が ae_title と違えば Association を断る
    require_called_ae_title: bool = True

    @field_validator("ae_title")
    @classmethod
    def _check_ae_title(cls, value: str) -> str:
        return validate_ae_title(value)


class Station(BaseModel):
    """装置の台帳の1台（docs/spec/03_web_cli.md 4 章）.

    `name` は画面と CLI で選ぶ運用上の名前で、MWL には入れない。`ae_title` は
    Scheduled Station AE Title (0040,0001)、`station_name` は Scheduled Station Name
    (0040,0010) に入れる。
    """

    model_config = {"frozen": True}

    name: str = Field(..., min_length=1, max_length=LO_MAX_LENGTH)
    ae_title: str
    station_name: str = Field("", max_length=SH_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not value.strip() or has_control_chars(value):
            raise ValueError("name must not be blank or contain control characters")
        return value

    @field_validator("ae_title")
    @classmethod
    def _check_ae_title(cls, value: str) -> str:
        return validate_ae_title(value)

    @field_validator("station_name")
    @classmethod
    def _check_station_name(cls, value: str) -> str:
        """SH（16 字まで、`\\` と制御文字なし。PS3.5 6.2）."""
        if "\\" in value or has_control_chars(value):
            raise ValueError("station_name must not contain backslash or control characters")
        return value


class ModalityCatalog(BaseModel):
    """モダリティごとの装置の台帳と検査の種類."""

    model_config = {"frozen": True}

    stations: list[Station] = Field(..., min_length=1)
    procedures: list[Procedure] = Field(..., min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _reject_old_keys(cls, data: Any) -> Any:
        """古い形（station_ae_titles・station_name）は推測で変換せずに断る."""
        if isinstance(data, dict) and ({"station_ae_titles", "station_name"} & data.keys()):
            raise ValueError(
                "station_ae_titles and station_name are no longer supported; write stations: "
                '[{name: "CT1号機", ae_title: "CT01", station_name: "CT01"}] instead'
            )
        return data

    def station(self, name: str) -> Station | None:
        return next((station for station in self.stations if station.name == name), None)


class OrdersConfig(BaseModel):
    model_config = {"frozen": True}

    institution_name: str = Field("TEST HOSPITAL", max_length=64)
    accession_prefix: str = Field("RE", max_length=ACCESSION_PREFIX_MAX_LENGTH)
    patient_id_prefix: str = Field("RE", max_length=PATIENT_ID_PREFIX_MAX_LENGTH)
    # Issuer of Patient ID と Issuer of Accession Number Sequence の Local Namespace Entity ID。
    # 空なら返さない（docs/spec/04_identifiers.md の 2 章、ADR-0005）
    issuer_namespace: str = "RIS_EMU"
    default_character_set: CharacterSet = CharacterSet.UTF8
    roster_path: str = "data/patients_sample.yaml"
    departments: list[str] = Field(default_factory=lambda: ["内科"], min_length=1)
    modalities: dict[str, ModalityCatalog] = Field(..., min_length=1)
    # 撮り直しの扱い（docs/spec/01_orders.md 7 章、ADR-0008）。append は IHE の Append Case で
    # RIS は何もしない。new_order は撮り直しの予約を作る（施設のローカルルール）
    retake_mode: RetakeMode = "append"

    @field_validator("accession_prefix", "patient_id_prefix")
    @classmethod
    def _check_prefix(cls, value: str) -> str:
        if not value.isascii() or not value.isalnum():
            raise ValueError("prefix must be ASCII letters or digits")
        return value

    @field_validator("issuer_namespace")
    @classmethod
    def _check_issuer(cls, value: str) -> str:
        if value and not ISSUER_PATTERN.fullmatch(value):
            raise ValueError("issuer_namespace must be ASCII letters, digits or '_', 16 characters or fewer")
        return value

    @field_validator("modalities")
    @classmethod
    def _check_modalities(cls, values: dict[str, ModalityCatalog]) -> dict[str, ModalityCatalog]:
        for key in values:
            if not (key.isascii() and key.isalnum() and key.isupper() and len(key) <= 16):
                raise ValueError(f"modality '{key}' must be upper-case ASCII (e.g. CT, MR)")
        names = [station.name for catalog in values.values() for station in catalog.stations]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise ValueError(f"station names must be unique: {', '.join(duplicated)}")
        return values


class WebConfig(BaseModel):
    model_config = {"frozen": True}

    bind_address: str = "127.0.0.1"
    port: int = Field(8081, ge=PORT_MIN, le=PORT_MAX)
    start_mwl: bool = True  # 画面のプロセスで MWL の SCP も立てる


class AppConfig(BaseModel):
    model_config = {"frozen": True}

    database: str = "state/ris.sqlite3"
    mwl: MwlConfig = Field(default_factory=MwlConfig)
    orders: OrdersConfig
    web: WebConfig = Field(default_factory=WebConfig)

    @model_validator(mode="after")
    def _check_statuses(self) -> AppConfig:
        # 終わりの状態（完了・取消・中止）は MWL で返さない
        unsupported = {status for status in self.mwl.statuses if is_final(status)}
        if unsupported:
            names = ", ".join(sorted(status.value for status in unsupported))
            raise ValueError(f"mwl.statuses must not include {names}")
        return self


def load_config(path: Path, environ: Mapping[str, str] | None = None) -> AppConfig:
    """設定ファイルを読み、環境変数で待ち受けのアドレスを上書きする.

    `RIS_WEB_BIND_ADDRESS`・`RIS_MWL_BIND_ADDRESS` は、設定の `web.bind_address`・
    `mwl.bind_address` より先に効く（Docker のイメージで使う）。
    """
    config = _load_file(path)
    env = os.environ if environ is None else environ
    web_bind = env.get(WEB_BIND_ENV, "").strip()
    mwl_bind = env.get(MWL_BIND_ENV, "").strip()
    if web_bind:
        config = config.model_copy(
            update={"web": config.web.model_copy(update={"bind_address": web_bind})}
        )
    if mwl_bind:
        config = config.model_copy(
            update={"mwl": config.mwl.model_copy(update={"bind_address": mwl_bind})}
        )
    return config


def _load_file(path: Path) -> AppConfig:
    """設定ファイルを読む。読めない・形が違えば ConfigurationError."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError("Config file not found", {"path": str(path)}) from exc
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError("Config file could not be read", {"path": str(path)}) from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("Config file must be a mapping", {"path": str(path)})
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise ConfigurationError(
            f"Invalid config: {location}: {first['msg']}", {"path": str(path)}
        ) from exc
