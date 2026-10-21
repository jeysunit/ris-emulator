"""設定ファイル（config/app_config.yaml）の読み込み（spec/03_web_cli.md 4 章）.

相対のパスは、プロセスの作業ディレクトリから辿る。
環境変数 `RIS_WEB_BIND_ADDRESS`・`RIS_MWL_BIND_ADDRESS` があれば、待ち受けのアドレスを上書きする。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import ConfigurationError
from app.core.models import CharacterSet, OrderStatus, Procedure, validate_ae_title

PORT_MIN = 1
PORT_MAX = 65535
DEFAULT_MAX_RESULTS = 1000
MAX_RESULTS_LIMIT = 100_000
ACCESSION_PREFIX_MAX_LENGTH = 4
PATIENT_ID_PREFIX_MAX_LENGTH = 8
ISSUER_PATTERN = re.compile(r"[A-Za-z0-9_]{1,16}")
WEB_BIND_ENV = "RIS_WEB_BIND_ADDRESS"
MWL_BIND_ENV = "RIS_MWL_BIND_ADDRESS"


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


class ModalityCatalog(BaseModel):
    """モダリティごとの予定の装置と検査の種類."""

    model_config = {"frozen": True}

    station_ae_titles: list[str] = Field(..., min_length=1)
    station_name: str = ""
    procedures: list[Procedure] = Field(..., min_length=1)

    @field_validator("station_ae_titles")
    @classmethod
    def _check_ae_titles(cls, values: list[str]) -> list[str]:
        return [validate_ae_title(value) for value in values]


class OrdersConfig(BaseModel):
    model_config = {"frozen": True}

    institution_name: str = Field("TEST HOSPITAL", max_length=64)
    accession_prefix: str = Field("RE", max_length=ACCESSION_PREFIX_MAX_LENGTH)
    patient_id_prefix: str = Field("RE", max_length=PATIENT_ID_PREFIX_MAX_LENGTH)
    # Issuer of Patient ID と Issuer of Accession Number Sequence の Local Namespace Entity ID。
    # 空なら返さない（spec/04_identifiers.md の 3 章）
    issuer_namespace: str = "RIS_EMU"
    default_character_set: CharacterSet = CharacterSet.UTF8
    roster_path: str = "data/patients_sample.yaml"
    departments: list[str] = Field(default_factory=lambda: ["内科"], min_length=1)
    modalities: dict[str, ModalityCatalog] = Field(..., min_length=1)

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
        unsupported = {OrderStatus.COMPLETED, OrderStatus.CANCELLED} & set(self.mwl.statuses)
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
