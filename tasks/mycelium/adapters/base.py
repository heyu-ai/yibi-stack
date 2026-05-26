"""帳號偵測 adapter 抽象介面。"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AccountAdapter(ABC):
    """帳號偵測 adapter 的抽象介面。每個 Agent 一個子類。"""

    agent_type: str = ""  # 子類必須設定

    @abstractmethod
    def detect(self) -> str | None:
        """偵測帳號 email。無法偵測時回傳 None，絕對不拋例外。"""
        ...
