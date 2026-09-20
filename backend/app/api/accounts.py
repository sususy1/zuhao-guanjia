from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
import threading, logging, json, uuid, time
from datetime import datetime
from ..database import get_db, SessionLocal
from ..auth import get_current_user
from .. import models, schemas
from ..platforms.registry import get_platform_adapter, PLATFORM_REGISTRY
from ..auto_login import supports_auto_login, do_auto_login, mima_login_with_code, mima_send_sms

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["账号"])

# 自动登录任务状态存储
_auto_login_tasks = {}
_auto_login_lock = threading.Lock()


def _sync_account_background(account_id: int):
    """后台线程同步账号数据"""
    db = SessionLocal()
    try:
        account = db.query(models.RentalAccount).filter(models.RentalAccount.id == account_id).first()
        if not account:
            return
        adapter = get_platform_adapter(account.platform)
        if not adapter:
            account.status = "error"
            account.error_message = "平台不支持"
            db.commit()
            return
        try:
            # 同步商品
            adapter.sync_listings(account, db)
            # 同步订单
            adapter.sync_orders(account, db)
            account.status = "online"
            account.error_message = None
            account.last_sync_time = datetime.utcnow()
            db.commit()
            logger.info(f"账号 {account.id} 同步成功")
        except Exception as e:
            logger.error(f"账号 {account.id} 同步失败: {e}")
            account.status = "error"
            account.error_message = str(e)[:500]
            db.commit()
    finally:
        db.close()


@router.get("", response_model=List[schemas.RentalAccountResponse])
def list_accounts(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    accounts = db.query(models.RentalAccount).filter(models.RentalAccount.user_id == current_user.id).order_by(models.RentalAccount.id).all()
    return accounts


@router.post("", response_model=schemas.RentalAccountResponse)
def create_account(data: schemas.RentalAccountCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if data.platform not in PLATFORM_REGISTRY:
        raise HTTPException(status_code=400, detail="不支持的平台")
    account = models.RentalAccount(
        user_id=current_user.id,
        platform=data.platform,
        platform_username=data.platform_username,
        platform_password=data.platform_password,
        nickname=data.nickname or data.platform_username,
        group_name=data.group_name,
        auto_manage=data.auto_manage,
        onshelf_start_time=data.onshelf_start_time,
        onshelf_end_time=data.onshelf_end_time,
        rental_frequency=data.rental_frequency,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=schemas.RentalAccountResponse)
def get_account(account_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


@router.put("/{account_id}", response_model=schemas.RentalAccountResponse)
def update_account(account_id: int, data: schemas.RentalAccountUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(account, key, value)
    account.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    db.delete(account)
    db.commit()
    return {"success": True}


@router.post("/{account_id}/sync")
def sync_account(account_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    thread = threading.Thread(target=_sync_account_background, args=(account_id,), daemon=True)
    thread.start()
    return {"code": 0, "message": "同步任务已启动"}


@router.get("/{account_id}/listings", response_model=dict)
def list_listings(
    account_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    query = db.query(models.Listing).filter(models.Listing.account_id == account_id)
    if status:
        query = query.filter(models.Listing.status == status)
    total = query.count()
    listings = query.order_by(models.Listing.id).offset((page-1)*page_size).limit(page_size).all()
    return {"total": total, "items": [schemas.ListingResponse.from_orm(l) for l in listings]}


@router.put("/{account_id}/listings/{listing_id}", response_model=schemas.ListingResponse)
def update_listing(
    account_id: int,
    listing_id: int,
    data: schemas.ListingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id, models.Listing.account_id == account_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="商品不存在")
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(listing, key, value)
    listing.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(listing)
    return listing


@router.post("/{account_id}/listings/{listing_id}/action")
def listing_action(
    account_id: int,
    listing_id: int,
    data: schemas.ListingActionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    account = db.query(models.RentalAccount).filter(
        models.RentalAccount.id == account_id, models.RentalAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id, models.Listing.account_id == account_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="商品不存在")
    adapter = get_platform_adapter(account.platform)
    if not adapter:
        raise HTTPException(status_code=400, detail="平台不支持")
    if data.action == "onshelf":
        result = adapter.onshelf_listing(account, listing, db)
    elif data.action == "offshelf":
        result = adapter.offshelf_listing(account, listing, db)
    else:
        raise HTTPException(status_code=400, detail="不支持的操作")
    return result


@router.get("/listings/grouped")
def get_grouped_listings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """按account_identifier分组的商品列表"""
    listings = db.query(models.Listing).join(models.RentalAccount).filter(
        models.RentalAccount.user_id == current_user.id).all()
    groups = {}
    for l in listings:
        key = l.account_identifier or "未设置"
        if key not in groups:
            groups[key] = []
        groups[key].append(schemas.ListingResponse.from_orm(l))
    result = []
    for ident, items in groups.items():
        result.append({
            "account_identifier": ident,
            "count": len(items),
            "listings": items
        })
    return result


@router.post("/conflict-check")
def run_conflict_check(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """手动触发冲突检测"""
    try:
        from ..conflict_detector import check_all_conflicts
        result = check_all_conflicts(db, current_user.id)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _auto_login_background(task_id: str, user_id: int, platform: str,
                            username: str, password: str, nickname: str, group_name: str):
    """后台线程执行自动登录"""
    db = SessionLocal()
    try:
        with _auto_login_lock:
            task = _auto_login_tasks.get(task_id)
            if task:
                task["status"] = "running"
                task["progress"] = "开始自动登录..."

        def progress_callback(msg):
            with _auto_login_lock:
                task = _auto_login_tasks.get(task_id)
                if task:
                    task["progress"] = msg

        try:
            # 执行自动登录
            cookies = do_auto_login(platform, username, password, progress_callback)
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])

            # 创建或更新账号
            account = db.query(models.RentalAccount).filter(
                models.RentalAccount.user_id == user_id,
                models.RentalAccount.platform == platform,
                models.RentalAccount.platform_username == username
            ).first()

            if not account:
                account = models.RentalAccount(
                    user_id=user_id,
                    platform=platform,
                    platform_username=username,
                    platform_password=password,
                    nickname=nickname or username,
                    group_name=group_name,
                    cookie_data=cookie_str,
                    status="online",
                )
                db.add(account)
            else:
                account.cookie_data = cookie_str
                account.platform_password = password
                account.status = "online"
                account.error_message = None

            db.commit()
            db.refresh(account)

            # 启动同步
            thread = threading.Thread(target=_sync_account_background, args=(account.id,), daemon=True)
            thread.start()

            with _auto_login_lock:
                task = _auto_login_tasks.get(task_id)
                if task:
                    task["status"] = "success"
                    task["account_id"] = account.id
                    task["cookie_data"] = cookie_str[:100] + "..." if len(cookie_str) > 100 else cookie_str
                    task["progress"] = "登录成功，开始同步数据..."

            logger.info(f"自动登录成功: task={task_id}, account={account.id}")

        except Exception as e:
            logger.error(f"自动登录失败: task={task_id}, error={e}")
            with _auto_login_lock:
                task = _auto_login_tasks.get(task_id)
                if task:
                    task["status"] = "failed"
                    task["message"] = str(e)[:500]
                    task["progress"] = f"登录失败: {e}"
    finally:
        db.close()


@router.post("/auto-login", response_model=schemas.AutoLoginResponse)
def start_auto_login(data: schemas.AutoLoginRequest,
                     current_user: models.User = Depends(get_current_user)):
    """启动平台自动登录任务"""
    if not supports_auto_login(data.platform):
        raise HTTPException(status_code=400, detail=f"平台 {data.platform} 暂不支持自动登录")

    task_id = str(uuid.uuid4())
    with _auto_login_lock:
        _auto_login_tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": "任务已创建，等待执行...",
            "created_at": time.time(),
        }

    thread = threading.Thread(
        target=_auto_login_background,
        args=(task_id, current_user.id, data.platform,
              data.platform_username, data.platform_password,
              data.nickname, data.group_name),
        daemon=True
    )
    thread.start()

    return {"task_id": task_id, "status": "pending", "message": "自动登录任务已启动"}


@router.get("/auto-login/{task_id}", response_model=schemas.AutoLoginStatusResponse)
def get_auto_login_status(task_id: str, current_user: models.User = Depends(get_current_user)):
    """查询自动登录任务状态"""
    with _auto_login_lock:
        task = _auto_login_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "task_id": task_id,
        "status": task.get("status", "pending"),
        "message": task.get("message"),
        "account_id": task.get("account_id"),
        "cookie_data": task.get("cookie_data"),
        "progress": task.get("progress"),
    }


@router.post("/mima-send-sms")
def mima_send_sms_code(data: dict, current_user: models.User = Depends(get_current_user)):
    """发送密马短信验证码"""
    phone = data.get("phone", "")
    if not phone:
        raise HTTPException(status_code=400, detail="手机号不能为空")
    result = mima_send_sms(phone)
    return result


@router.post("/mima-login")
def mima_login(data: dict, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    """密马半自动登录（手机号+短信验证码）"""
    phone = data.get("phone", "")
    code = data.get("code", "")
    nickname = data.get("nickname", "")
    group_name = data.get("group_name", "默认分组")

    if not phone or not code:
        raise HTTPException(status_code=400, detail="手机号和验证码不能为空")

    try:
        # 执行登录
        token_data = mima_login_with_code(phone, code)
        token = token_data.get("token", "")

        if not token:
            raise HTTPException(status_code=500, detail="登录成功但未获取到Token")

        # 创建或更新账号
        account = db.query(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id,
            models.RentalAccount.platform == "mima",
            models.RentalAccount.platform_username == phone
        ).first()

        if not account:
            account = models.RentalAccount(
                user_id=current_user.id,
                platform="mima",
                platform_username=phone,
                platform_password="",  # 密马是验证码登录，没有密码
                nickname=nickname or phone,
                group_name=group_name,
                token_data=token,
                status="online",
            )
            db.add(account)
        else:
            account.token_data = token
            account.status = "online"
            account.error_message = None

        db.commit()
        db.refresh(account)

        # 启动同步
        thread = threading.Thread(target=_sync_account_background, args=(account.id,), daemon=True)
        thread.start()

        return {
            "success": True,
            "message": "登录成功",
            "account_id": account.id,
            "token": token[:50] + "..." if len(token) > 50 else token,
        }

    except Exception as e:
        logger.error(f"密马登录失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
