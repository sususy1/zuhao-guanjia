from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
import threading, logging, json
from datetime import datetime
from ..database import get_db, SessionLocal
from ..auth import get_current_user
from .. import models, schemas
from ..platforms.registry import get_platform_adapter, PLATFORM_REGISTRY

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["账号"])


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
