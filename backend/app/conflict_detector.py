"""
跨平台冲突检测模块
检测到一个平台的账号有出租中订单时，自动下架其他平台同账号的商品
"""
import logging, json
from sqlalchemy.orm import Session
from . import models
from .platforms.registry import get_platform_adapter

logger = logging.getLogger(__name__)


def check_all_conflicts(db: Session, user_id: int) -> dict:
    """检查所有账号的跨平台冲突"""
    result = {"detected": 0, "auto_offshelfed": 0, "details": []}

    # 1. 找出所有进行中的订单
    ongoing_orders = db.query(models.Order).join(models.RentalAccount).filter(
        models.RentalAccount.user_id == user_id,
        models.Order.status == "ongoing"
    ).all()

    if not ongoing_orders:
        return result

    # 2. 对每个进行中的订单，找到对应商品的account_identifier
    for order in ongoing_orders:
        try:
            # 从订单platform_data提取goods_id
            goods_id = None
            if order.platform_data:
                try:
                    pd = json.loads(order.platform_data) if isinstance(order.platform_data, str) else order.platform_data
                    goods_id = str(pd.get("goods_id") or pd.get("goodsId") or "")
                except Exception:
                    pass

            # 找到对应商品
            listing = None
            if order.listing_id:
                listing = db.query(models.Listing).filter(models.Listing.id == order.listing_id).first()
            elif goods_id:
                listing = db.query(models.Listing).filter(
                    models.Listing.account_id == order.account_id,
                    models.Listing.platform_listing_id == goods_id).first()

            if not listing or not listing.account_identifier:
                continue

            account_identifier = listing.account_identifier
            source_platform = listing.account.platform if listing.account else None

            # 3. 查找其他平台同account_identifier且上架中的商品
            other_listings = db.query(models.Listing).join(models.RentalAccount).filter(
                models.RentalAccount.user_id == user_id,
                models.Listing.account_identifier == account_identifier,
                models.Listing.status == "on_shelf",
                models.Listing.id != listing.id
            ).all()

            if not other_listings:
                continue

            result["detected"] += 1
            detail = {
                "order_id": order.id,
                "account_identifier": account_identifier,
                "source_platform": source_platform,
                "conflicts": []
            }

            # 4. 自动下架冲突商品
            for other in other_listings:
                adapter = get_platform_adapter(other.account.platform)
                if adapter:
                    try:
                        res = adapter.offshelf_listing(other.account, other, db)
                        if res.get("success"):
                            result["auto_offshelfed"] += 1
                            detail["conflicts"].append({
                                "listing_id": other.id,
                                "platform": other.account.platform,
                                "title": other.title,
                                "action": "auto_offshelf"
                            })
                        else:
                            detail["conflicts"].append({
                                "listing_id": other.id,
                                "platform": other.account.platform,
                                "title": other.title,
                                "action": "failed",
                                "reason": res.get("message")
                            })
                    except Exception as e:
                        detail["conflicts"].append({
                            "listing_id": other.id,
                            "platform": other.account.platform,
                            "title": other.title,
                            "action": "error",
                            "reason": str(e)
                        })
                else:
                    # 没有适配器，只标记
                    other.status = "conflict"
                    db.commit()
                    detail["conflicts"].append({
                        "listing_id": other.id,
                        "platform": other.account.platform,
                        "title": other.title,
                        "action": "marked_conflict"
                    })

            result["details"].append(detail)
        except Exception as e:
            logger.error(f"冲突检测订单 {order.id} 出错: {e}")

    return result
