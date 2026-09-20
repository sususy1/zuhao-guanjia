from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from ..database import get_db
from ..auth import get_current_user
from .. import models, schemas

router = APIRouter(prefix="/api/orders", tags=["订单"])


@router.get("", response_model=dict)
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Order).join(models.RentalAccount).filter(models.RentalAccount.user_id == current_user.id)
    if account_id:
        query = query.filter(models.Order.account_id == account_id)
    if status:
        query = query.filter(models.Order.status == status)
    total = query.count()
    orders = query.order_by(desc(models.Order.created_at)).offset((page-1)*page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [schemas.OrderResponse.from_orm(o) for o in orders]
    }


@router.get("/{order_id}", response_model=schemas.OrderResponse)
def get_order(order_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    order = db.query(models.Order).join(models.RentalAccount).filter(
        models.Order.id == order_id, models.RentalAccount.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order
