"""例外の階層."""

from __future__ import annotations


class RisEmulatorError(Exception):
    """ベースの例外."""

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class ConfigurationError(RisEmulatorError):
    """設定ファイル・名簿の誤り."""


class ValidationError(RisEmulatorError):
    """CLI・画面から入った値の誤り."""


class OrderNotFoundError(RisEmulatorError):
    """受付番号に当たる予約が無い."""


class MwlServerError(RisEmulatorError):
    """MWL の SCP を起動できない."""
