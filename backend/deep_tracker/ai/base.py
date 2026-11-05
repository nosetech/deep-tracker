from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class AIError(Exception):
    """AI呼び出しの失敗の基底クラス。"""


class RateLimitError(AIError):
    """利用制限（サブスクリプション上限）への到達。待機はせず、呼び出し側で失敗として扱う。"""

    def __init__(self, message: str, reset_text: str | None = None):
        super().__init__(message)
        # 解除予定時刻。CLIの自由文から抜いたもので、取れなければ None
        self.reset_text = reset_text


class AITimeoutError(AIError):
    """AI呼び出しがタイムアウトした。"""


class AIUnavailableError(AIError):
    """AIのCLI等が見つからず、呼び出せない。"""


@dataclass(frozen=True)
class AIResult:
    text: str
    usage: dict = field(default_factory=dict)


class AIProvider(ABC):
    @abstractmethod
    def generate(
        self, prompt: str, *, system_prompt: str | None = None, input_text: str | None = None
    ) -> AIResult:
        """指示を渡して結果テキストを返す。

        input_text は記事本文などの長い入力。引数長の上限を避けるため標準入力等で渡す。
        失敗は AIError のサブクラスとして送出する。
        """
