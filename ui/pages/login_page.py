# -*- coding: utf-8 -*-
"""ERP 登录页 Page Object。

定位器来自云端 jshERP 登录页真实 DOM 与 Playwright 探测：
入口打开 UI 根地址，前端路由到 /user/login，登录后进入 /dashboard/analysis。
"""
import base64
import io
import warnings
from typing import List, Optional

import ddddocr
from config.settings import ERP_UI_URL, UI_LOGIN_SUCCESS_KIND, UI_LOGIN_SUCCESS_VALUE
from PIL import Image, ImageFilter, ImageOps
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from ui.pages.base_page import BasePage


class LoginPage(BasePage):
    LOGIN_PATH: Optional[str] = "/"
    USERNAME_SELECTOR: Optional[str] = "#loginName"
    PASSWORD_SELECTOR: Optional[str] = "#password"
    CAPTCHA_IMAGE_SELECTOR: Optional[str] = "form#formLogin img[src^='data:image']"
    CAPTCHA_INPUT_SELECTOR: Optional[str] = "#inputCode"
    LOGIN_BUTTON_TEXT: Optional[str] = "登 录"
    DEFAULT_SUCCESS_KIND = "url"
    DEFAULT_SUCCESS_VALUE = "**/dashboard/analysis"
    MAX_LOGIN_ATTEMPTS = 3

    @classmethod
    def missing_materials(cls) -> List[str]:
        """列出登录页尚缺的真实页面资料；资料齐全前 UI 用例在启动浏览器前跳过"""
        missing = []
        if not cls.LOGIN_PATH:
            missing.append("登录入口路径")
        if cls.USERNAME_SELECTOR is None:
            missing.append("用户名输入框定位")
        if cls.PASSWORD_SELECTOR is None:
            missing.append("密码输入框定位")
        if cls.CAPTCHA_IMAGE_SELECTOR is None:
            missing.append("验证码图片定位")
        if cls.CAPTCHA_INPUT_SELECTOR is None:
            missing.append("验证码输入框定位")
        if cls.LOGIN_BUTTON_TEXT is None:
            missing.append("登录按钮定位")
        return missing

    def open(self) -> None:
        """打开真实 jshERP 登录页"""
        self.page.goto(
            ERP_UI_URL.rstrip("/") + self.LOGIN_PATH,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        self.page.locator(self.USERNAME_SELECTOR).wait_for(timeout=15000)

    def login(self, username: str, password: str) -> None:
        """填写账号、密码和页面验证码后登录；最多重试3次"""
        last_error = None

        for attempt in range(1, self.MAX_LOGIN_ATTEMPTS + 1):
            if attempt > 1:
                self.open()

            try:
                self.page.locator(self.USERNAME_SELECTOR).fill(username)
                self.page.locator(self.PASSWORD_SELECTOR).fill(password)
                self.page.locator(self.CAPTCHA_INPUT_SELECTOR).fill(
                    self._read_page_captcha()
                )

                with self.page.expect_response(
                    lambda r: r.request.method == "POST" and "/user/login" in r.url,
                    timeout=10000,
                ) as response_info:
                    self.page.get_by_role(
                        "button", name=self.LOGIN_BUTTON_TEXT
                    ).click()

                response = response_info.value
                result = response.json()
                data = result.get("data")
                data = data if isinstance(data, dict) else {}

                print(
                    f"[UI登录接口] HTTP={response.status}, "
                    f"code={result.get('code')}, "
                    f"message={data.get('message') or result.get('msg') or result.get('msgTip')}",
                    flush=True,
                )

                self._wait_logged_in(timeout=15000)
                self._close_optional_home_overlays()
                return

            except (RuntimeError, PlaywrightTimeoutError) as error:
                print(
                    f"[UI登录] 第{attempt}次失败，"
                    f"当前URL={self.page.url}，"
                    f"错误={type(error).__name__}: {error}",
                    flush=True,
                )
                last_error = error

        raise RuntimeError(
            f"登录失败：连续{self.MAX_LOGIN_ATTEMPTS}次未成功"
        ) from last_error

    def assert_logged_in(self, timeout: int = 15000) -> None:
        """按配置校验登录成功。

        kind=url 等待目标 URL；kind=title 校验页面标题；kind=text 等待稳定可见元素。
        value 必须来自真实 jshERP 页面资料，不允许猜测。
        """
        kind = UI_LOGIN_SUCCESS_KIND or self.DEFAULT_SUCCESS_KIND
        value = UI_LOGIN_SUCCESS_VALUE or self.DEFAULT_SUCCESS_VALUE
        self._wait_logged_in(kind=kind, value=value, timeout=timeout)

    def _wait_logged_in(self, kind: str = "", value: str = "", timeout: int = 15000) -> None:
        kind = kind or UI_LOGIN_SUCCESS_KIND or self.DEFAULT_SUCCESS_KIND
        value = value or UI_LOGIN_SUCCESS_VALUE or self.DEFAULT_SUCCESS_VALUE
        if kind == "url":
            self.page.wait_for_url(value, wait_until="domcontentloaded", timeout=timeout)
        elif kind == "title":
            self.wait_for_title(value, timeout=timeout)
        elif kind == "text":
            self.wait_visible_text(value, timeout=timeout)
        else:
            raise RuntimeError(
                f"不支持的登录成功判断方式: {kind}（仅支持 url/title/text）"
            )

    def _read_page_captcha(self) -> str:
        """识别当前登录页展示的验证码图片"""
        src = self.page.locator(self.CAPTCHA_IMAGE_SELECTOR).get_attribute("src")
        if not src or "," not in src:
            raise RuntimeError("未获取到登录页验证码图片")
        img_bytes = base64.b64decode(src.split(",", 1)[1])
        pil = Image.open(io.BytesIO(img_bytes)).convert("L")
        pil = ImageOps.autocontrast(pil, cutoff=5)
        pil = pil.filter(ImageFilter.SHARPEN)
        pil = pil.point(lambda x: 0 if x < 128 else 255, "1")
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            code = ddddocr.DdddOcr(beta=False, show_ad=False).classification(buf.getvalue())
        if len(code) != 4:
            raise RuntimeError("登录页验证码识别失败")
        return code

    def _close_optional_home_overlays(self) -> None:
        """关闭登录后首页可能出现的操作引导或缩放提示"""
        for name in ("×", "关闭"):
            target = self.page.get_by_role("button", name=name)
            if target.count():
                try:
                    target.first.click(timeout=1000)
                except Exception:
                    pass
        close_icon = self.page.locator(".ant-notification-close-icon")
        if close_icon.count():
            try:
                close_icon.first.click(timeout=1000)
            except Exception:
                pass
