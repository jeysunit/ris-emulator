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


class InvalidTransitionError(ValidationError):
    """遷移の表に無い向きへ予約の状態を変えようとした."""


class OrderNotFoundError(RisEmulatorError):
    """受付番号に当たる予約が無い."""


class MwlServerError(RisEmulatorError):
    """MWL の SCP を起動できない."""


class AckParseError(RisEmulatorError):
    """HL7 の ACK を読めない（MSH・MSA が無い、区切りの定義が違う）."""


class MppsError(RisEmulatorError):
    """MPPS の N-CREATE・N-SET を受け付けられない."""


class DuplicateMppsError(MppsError):
    """同じ SOP Instance UID の MPPS がすでにある（0111H）."""


class MppsNotFoundError(MppsError):
    """N-SET の対象の MPPS が無い（0112H）."""


class MppsNotInProgressError(MppsError):
    """N-SET の対象の MPPS が IN PROGRESS でない（0110H、Error ID A710）."""


class AlreadyReconciledError(ValidationError):
    """MPPS がすでに予約に結び付いている（照合済み、または予約どおりの撮影）."""


class ReconciliationNotFoundError(RisEmulatorError):
    """受付番号に当たる照合の記録が無い."""
