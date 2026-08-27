import unittest
from threading import Event

import json
import os
import tempfile

from crawler.accounts import load_platform_credentials
from crawler.auth import Credentials, LoginCoordinator
from crawler.engine import CrawlerEngine
from crawler.models import CompanyInfo


class FakeElement:
    def __init__(self, text="", displayed=True, enabled=True):
        self.text = text
        self._displayed = displayed
        self._enabled = enabled
        self.value = ""
        self.clicked = False
        self.size = {"width": 100, "height": 24 if displayed else 0}

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return self._enabled

    def clear(self):
        self.value = ""

    def send_keys(self, value):
        self.value += value

    def click(self):
        self.clicked = True


class FakeDriver:
    def __init__(self):
        self.current_url = "https://www.zhipin.com/web/user/"
        self.title = "登录"
        self.elements = {}

    def find_elements(self, by, selector):
        return self.elements.get(selector, [])

    def get(self, url):
        self.current_url = url


class CrawlerUnitTests(unittest.TestCase):
    def test_load_credentials_from_file(self):
        payload = {"boss": {"username": "13800000000", "password": "secret"}}
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8",
        ) as f:
            json.dump(payload, f)
            path = f.name
        try:
            creds = load_platform_credentials("boss", path)
            self.assertIsNotNone(creds)
            self.assertEqual(creds.username, "13800000000")
            self.assertEqual(creds.password, "secret")
        finally:
            os.remove(path)

    def test_credentials_clear(self):
        credentials = Credentials("13800000000", "secret")
        credentials.clear()
        self.assertEqual(credentials.username, "")
        self.assertEqual(credentials.password, "")

    def test_login_prefill(self):
        driver = FakeDriver()
        phone = FakeElement()
        password = FakeElement()
        driver.elements["input[type='tel']"] = [phone]
        driver.elements["input[type='password']"] = [password]
        coordinator = LoginCoordinator(driver, Event(), lambda _: None)

        coordinator._prefill_boss(Credentials("13800000000", "secret"))

        self.assertEqual(phone.value, "13800000000")
        self.assertEqual(password.value, "secret")

    def test_parse_page_deduplicates(self):
        def parser(item):
            return CompanyInfo(
                platform="测试", name=item.text, industry="", scale="",
                stage="", description="", location="北京",
                hot_jobs="Python", salary="",
                contact_person="", contact_info="",
            )

        cfg = {"parse_fn": parser}
        seen = set()
        data = CrawlerEngine._parse_page(
            [FakeElement("A公司"), FakeElement("A公司"), FakeElement("B公司")],
            cfg,
            seen,
        )
        self.assertEqual([item.name for item in data], ["A公司", "B公司"])

    def test_interruptible_delay_returns_when_stopped(self):
        event = Event()
        event.set()
        CrawlerEngine._interruptible_delay(event)
        self.assertTrue(event.is_set())

    def test_page_signature_uses_first_three_items(self):
        signature = CrawlerEngine._page_signature(
            [FakeElement("A"), FakeElement("B"), FakeElement("C"), FakeElement("D")]
        )
        self.assertEqual(signature, ("A", "B", "C"))

    def test_next_page_stops_when_no_button_or_new_url(self):
        driver = FakeDriver()
        driver.current_url = "https://example.test/search"
        cfg = {
            "item_css": ".job",
            "next_css": ".next",
            "url_tpl": "https://example.test/search",
        }
        moved = CrawlerEngine()._go_next_page(
            driver, cfg, 1, "Python", "", Event()
        )
        self.assertFalse(moved)

    def test_captcha_detection_ignores_hidden_widget_after_results_render(self):
        driver = FakeDriver()
        driver.title = "拉勾网"
        driver.elements[".job"] = [FakeElement("职位卡片")]
        driver.elements[".captcha"] = [FakeElement(displayed=False)]
        cfg = {
            "item_css": ".job",
            "captcha_css": ".captcha",
            "captcha_body_keywords": ["验证失败"],
        }

        self.assertFalse(CrawlerEngine._detect_captcha(driver, cfg))


if __name__ == "__main__":
    unittest.main()
