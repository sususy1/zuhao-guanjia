"""
定时任务调度器
- 每3分钟执行一次冲突检测
- 每30分钟同步一次所有账号数据
"""
import logging, threading
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from . import models
from .conflict_detector import check_all_conflicts
from .platforms.registry import get_platform_adapter
from datetime import datetime

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def sync_all_accounts():
    """同步所有账号数据"""
    db = SessionLocal()
    try:
        accounts = db.query(models.RentalAccount).filter(models.RentalAccount.auto_manage == True).all()
        for account in accounts:
            try:
                adapter = get_platform_adapter(account.platform)
                if adapter:
                    adapter.sync_listings(account, db)
                    adapter.sync_orders(account, db)
                    account.status = "online"
                    account.last_sync_time = datetime.utcnow()
                    db.commit()
            except Exception as e:
                logger.error(f"定时同步账号 {account.id} 失败: {e}")
                account.status = "error"
                account.error_message = str(e)[:500]
                db.commit()
    finally:
        db.close()


def run_conflict_check():
    """执行冲突检测"""
    db = SessionLocal()
    try:
        # 获取所有用户
        users = db.query(models.User).all()
        for user in users:
            try:
                result = check_all_conflicts(db, user.id)
                if result.get("detected", 0) > 0:
                    logger.info(f"冲突检测: 用户 {user.id} 发现 {result['detected']} 个冲突, 自动下架 {result['auto_offshelfed']} 个")
            except Exception as e:
                logger.error(f"冲突检测用户 {user.id} 失败: {e}")
    finally:
        db.close()


def start_scheduler():
    """启动调度器"""
    if scheduler.running:
        return
    # 每3分钟冲突检测
    scheduler.add_job(run_conflict_check, "interval", minutes=3, id="conflict_check")
    # 每30分钟同步所有账号
    scheduler.add_job(sync_all_accounts, "interval", minutes=30, id="sync_all")
    scheduler.start()
    logger.info("定时任务调度器已启动")


def stop_scheduler():
    """停止调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("定时任务调度器已停止")
