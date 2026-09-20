from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from ..database import get_db
from ..auth import get_current_user
from .. import models, schemas

router = APIRouter(prefix="/api/stats", tags=["统计"])


@router.get("/overview", response_model=schemas.StatsOverview)
def get_overview(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = datetime(now.year, now.month, 1)

    def _income(start):
        return db.query(func.coalesce(func.sum(models.Order.amount), 0)).join(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id,
            models.Order.created_at >= start, models.Order.status == "completed").scalar() or 0

    def _orders(start):
        return db.query(func.count(models.Order.id)).join(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id, models.Order.created_at >= start).scalar() or 0

    return schemas.StatsOverview(
        today_income=round(float(_income(today_start)), 2),
        today_orders=_orders(today_start),
        today_hours=round(float(db.query(func.coalesce(func.sum(models.Order.duration_hours), 0)).join(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id, models.Order.created_at >= today_start).scalar() or 0), 1),
        week_income=round(float(_income(week_start)), 2),
        week_orders=_orders(week_start),
        month_income=round(float(_income(month_start)), 2),
        month_orders=_orders(month_start),
        total_accounts=db.query(func.count(models.RentalAccount.id)).filter(models.RentalAccount.user_id == current_user.id).scalar() or 0,
        online_accounts=db.query(func.count(models.RentalAccount.id)).filter(
            models.RentalAccount.user_id == current_user.id, models.RentalAccount.status == "online").scalar() or 0,
        total_listings=db.query(func.count(models.Listing.id)).join(models.RentalAccount).filter(models.RentalAccount.user_id == current_user.id).scalar() or 0,
        on_shelf_listings=db.query(func.count(models.Listing.id)).join(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id, models.Listing.status == "on_shelf").scalar() or 0,
        total_game_accounts=db.query(func.count(func.distinct(models.Listing.account_identifier))).join(models.RentalAccount).filter(
            models.RentalAccount.user_id == current_user.id, models.Listing.account_identifier.isnot(None), models.Listing.account_identifier != "").scalar() or 0,
    )


@router.get("/daily", response_model=list[schemas.DailyStatResponse])
def get_daily_stats(days: int = 7, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    now = datetime.now()
    start_date = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    results = db.query(
        func.date(models.Order.created_at).label("date"),
        func.count(models.Order.id).label("total_orders"),
        func.coalesce(func.sum(models.Order.amount), 0).label("total_income"),
        func.coalesce(func.sum(models.Order.duration_hours), 0).label("total_hours"),
    ).join(models.RentalAccount).filter(
        models.RentalAccount.user_id == current_user.id, models.Order.created_at >= start_date
    ).group_by(func.date(models.Order.created_at)).all()

    stats_map = {}
    for r in results:
        d = r.date.strftime("%Y-%m-%d") if hasattr(r.date, "strftime") else str(r.date)
        stats_map[d] = schemas.DailyStatResponse(date=d, total_orders=r.total_orders or 0,
            total_income=round(float(r.total_income or 0), 2), total_hours=round(float(r.total_hours or 0), 1), abnormal_orders=0)

    daily_list = []
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily_list.append(stats_map.get(d, schemas.DailyStatResponse(date=d, total_orders=0, total_income=0, total_hours=0, abnormal_orders=0)))
    return daily_list
