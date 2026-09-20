"""
远程浏览器登录API
用户自己在网页上登录平台，服务器只负责采集数据
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime

from ..database import get_db
from ..auth import get_current_user
from .. import models
from ..browser_session import (
    create_session, get_session, close_session,
    PLATFORM_LOGIN_URLS
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/browser", tags=["远程浏览器登录"])


class CreateSessionRequest(BaseModel):
    platform: str


class ClickRequest(BaseModel):
    x: float
    y: float


class TypeRequest(BaseModel):
    text: str


class PressKeyRequest(BaseModel):
    key: str


class ConfirmLoginRequest(BaseModel):
    session_id: str
    nickname: Optional[str] = None
    group_name: Optional[str] = "默认分组"


@router.post("/session")
def create_browser_session(data: CreateSessionRequest, current_user: models.User = Depends(get_current_user)):
    """创建浏览器会话，打开平台登录页"""
    if data.platform not in PLATFORM_LOGIN_URLS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {data.platform}")

    try:
        session_id, screenshot = create_session(data.platform)
        return {
            "session_id": session_id,
            "platform": data.platform,
            "screenshot": screenshot,
            "message": "登录页已打开，请在截图上操作登录",
        }
    except Exception as e:
        logger.error(f"创建浏览器会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/screenshot")
def get_screenshot(session_id: str, current_user: models.User = Depends(get_current_user)):
    """获取当前页面截图"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    try:
        screenshot = session.screenshot()
        url = session.get_url()
        return {
            "session_id": session_id,
            "screenshot": screenshot,
            "current_url": url,
        }
    except Exception as e:
        logger.error(f"截图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/click")
def click_at(session_id: str, data: ClickRequest, current_user: models.User = Depends(get_current_user)):
    """在指定坐标点击"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    try:
        session.click(data.x, data.y)
        screenshot = session.screenshot()
        return {
            "session_id": session_id,
            "screenshot": screenshot,
            "message": "点击完成",
        }
    except Exception as e:
        logger.error(f"点击失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/type")
def type_text(session_id: str, data: TypeRequest, current_user: models.User = Depends(get_current_user)):
    """在当前焦点元素输入文字"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    try:
        session.type(data.text)
        screenshot = session.screenshot()
        return {
            "session_id": session_id,
            "screenshot": screenshot,
            "message": "输入完成",
        }
    except Exception as e:
        logger.error(f"输入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/press-key")
def press_key(session_id: str, data: PressKeyRequest, current_user: models.User = Depends(get_current_user)):
    """按键"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    try:
        session.press_key(data.key)
        screenshot = session.screenshot()
        return {
            "session_id": session_id,
            "screenshot": screenshot,
            "message": "按键完成",
        }
    except Exception as e:
        logger.error(f"按键失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{session_id}/confirm-login")
def confirm_login(session_id: str, data: ConfirmLoginRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """确认登录成功，获取Cookie并保存到账号"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    try:
        # 获取Cookie
        cookies = session.get_cookies()
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])

        # 获取当前URL，判断平台
        current_url = session.get_url()
        platform = None
        for p in PLATFORM_LOGIN_URLS:
            if p in current_url or p.replace("_", "") in current_url:
                platform = p
                break

        # 从会话存储中获取平台
        from ..browser_session import _sessions, _sessions_lock
        with _sessions_lock:
            session_data = _sessions.get(session_id)
            if session_data:
                platform = session_data.get("platform")

        if not platform:
            platform = "unknown"

        # 获取用户名（从Cookie中尝试提取）
        username = cookies.get("mobile") or cookies.get("username") or cookies.get("uid") or "user"

        # 密马特殊处理：从localStorage获取token
        token_data = None
        if platform == "mima":
            try:
                local_data = session.evaluate("() => JSON.stringify(window.localStorage)")
                import json
                local_dict = json.loads(local_data) if local_data else {}
                for key, value in local_dict.items():
                    if "token" in key.lower() or "jwt" in key.lower() or "auth" in key.lower():
                        token_data = str(value)
                        break
            except:
                pass

        # 创建或更新账号
        account = db.query(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id,
            models.RentalAccount.platform == platform,
            models.RentalAccount.platform_username == username
        ).first()

        if not account:
            account = models.RentalAccount(
                user_id=current_user.id,
                platform=platform,
                platform_username=username,
                platform_password="",
                nickname=data.nickname or username,
                group_name=data.group_name or "默认分组",
                cookie_data=cookie_str,
                token_data=token_data,
                status="online",
            )
            db.add(account)
        else:
            account.cookie_data = cookie_str
            if token_data:
                account.token_data = token_data
            account.status = "online"
            account.error_message = None

        db.commit()
        db.refresh(account)

        # 启动同步
        import threading
        from .accounts import _sync_account_background
        thread = threading.Thread(target=_sync_account_background, args=(account.id,), daemon=True)
        thread.start()

        # 关闭会话
        close_session(session_id)

        return {
            "success": True,
            "message": "登录成功，已保存凭证并开始同步数据",
            "account_id": account.id,
            "platform": platform,
            "username": username,
            "cookie_count": len(cookies),
        }

    except Exception as e:
        logger.error(f"确认登录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
def close_browser_session(session_id: str, current_user: models.User = Depends(get_current_user)):
    """关闭浏览器会话"""
    close_session(session_id)
    return {"success": True, "message": "会话已关闭"}


@router.get("/platforms")
def get_supported_platforms(current_user: models.User = Depends(get_current_user)):
    """获取支持远程登录的平台列表"""
    return {
        "platforms": [
            {"key": "uhaozu", "name": "U号租", "login_url": PLATFORM_LOGIN_URLS["uhaozu"]},
            {"key": "mima", "name": "密马", "login_url": PLATFORM_LOGIN_URLS["mima"]},
            {"key": "xubei", "name": "虚贝", "login_url": PLATFORM_LOGIN_URLS["xubei"]},
        ]
    }
