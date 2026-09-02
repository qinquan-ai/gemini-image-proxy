import asyncio

from src.core.browser import collect_gemini_login_evidence


class FakeLocator:
    def __init__(self, visible: bool = False, count: int = 0):
        self.visible = visible
        self.count_value = count

    def get_by_text(self, _text: str, exact: bool = False):
        return self

    async def is_visible(self) -> bool:
        return self.visible

    async def count(self) -> int:
        return self.count_value


class FakePage:
    def __init__(
        self,
        *,
        sign_in_link_count: int = 0,
        save_activity_sign_in_count: int = 0,
        account_control_count: int = 1,
        recent_chat_count: int = 0,
    ):
        self.sign_in_link = FakeLocator(count=sign_in_link_count)
        self.account_control = FakeLocator(count=account_control_count)
        self.save_activity_sign_in = FakeLocator(count=save_activity_sign_in_count)
        self.save_activity_sign_in_zh = FakeLocator(count=0)
        self.recent_chats = FakeLocator(count=recent_chat_count)

    def locator(self, selector: str) -> FakeLocator:
        if 'ServiceLogin' in selector or 'aria-label="登录"' in selector or 'aria-label="Sign in"' in selector:
            return self.sign_in_link
        if selector == 'a[href^="/app/"]':
            return self.recent_chats
        return self.account_control

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocator:
        if "登录以保存活动" in text:
            return self.save_activity_sign_in_zh
        return self.save_activity_sign_in


def check_evidence(**page_args):
    return asyncio.run(collect_gemini_login_evidence(FakePage(**page_args)))


def test_login_evidence_accepts_account_without_recent_chat_history():
    evidence = check_evidence(account_control_count=2, recent_chat_count=0)

    assert evidence.authenticated
    assert evidence.recent_chat_count == 0


def test_login_evidence_rejects_top_sign_in_link():
    evidence = check_evidence(sign_in_link_count=1, account_control_count=0)

    assert not evidence.authenticated
    assert evidence.sign_in_visible


def test_login_evidence_rejects_guest_save_activity_prompt():
    evidence = check_evidence(save_activity_sign_in_count=1, account_control_count=2)

    assert not evidence.authenticated
    assert evidence.save_activity_sign_in_visible


def test_login_evidence_rejects_missing_google_account_control():
    evidence = check_evidence(account_control_count=0)

    assert not evidence.authenticated
