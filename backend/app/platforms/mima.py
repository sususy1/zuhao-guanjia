"""
密马平台适配器
API: https://api.mimaapp.cn
认证: JWT Token (Authorization头)
注意: 不能带req-v头; fp头可为空; device:2
"""
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
import json, logging
from datetime import datetime
from .base import BasePlatformAdapter
from .. import models

logger = logging.getLogger(__name__)


class MiMaAdapter(BasePlatformAdapter):
    platform_key = "mima"
    platform_name = "密马"
    base_url = "https://api.mimaapp.cn"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "device": "2",
            "fp": "",
            "Referer": "https://www.mimaapp.com/",
            "Origin": "https://www.mimaapp.com",
        })

    def _set_token(self, account):
        if account.token_data:
            self.session.headers["Authorization"] = f"JWT {account.token_data}"

    def login(self, account, captcha=None):
        return {"success": False, "message": "密马登录需要验证码，请使用导入Token方式", "need_token": True}

    def sync_listings(self, account, db):
        self._set_token(account)
        listings = []
        try:
            page = 1
            while True:
                resp = self.session.get(
                    f"{self.base_url}/v4/goods/get_seller_goods",
                    params={"status": 1, "size": 50, "page": page},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"密马商品API错误: {data.get('msg')}")
                    break
                goods_list = data.get("data", {}).get("list", []) or []
                if not goods_list:
                    break
                for item in goods_list:
                    listing = self._parse_goods(item, account)
                    if listing:
                        listings.append(listing)
                total = data.get("data", {}).get("total", 0)
                if page * 50 >= total or len(goods_list) < 50:
                    break
                page += 1
        except Exception as e:
            logger.error(f"密马同步商品失败: {e}")

        if listings:
            existing = {l.platform_listing_id: l for l in db.query(models.Listing).filter(
                models.Listing.account_id == account.id).all()}
            for listing in listings:
                if listing.platform_listing_id in existing:
                    old = existing[listing.platform_listing_id]
                    old.title = listing.title
                    old.status = listing.status
                    old.price_per_hour = listing.price_per_hour
                    old.game_name = listing.game_name
                    old.account_identifier = listing.account_identifier
                    old.extra_data = listing.extra_data
                    old.updated_at = datetime.utcnow()
                else:
                    db.add(listing)
            db.commit()
        return listings

    def _parse_goods(self, item, account):
        goods_id = str(item.get("goods_id") or item.get("id") or "")
        if not goods_id:
            return None
        title = item.get("goods_name") or item.get("title", "未知商品")
        game_name = item.get("game_name", "")
        price = float(item.get("price") or item.get("rental_price") or 0)
        # 状态: 1=上架中, 2=已下架
        status_val = item.get("status", 0)
        if status_val == 1:
            status = "on_shelf"
        else:
            status = "off_shelf"
        account_identifier = item.get("game_account") or item.get("account") or item.get("qq") or goods_id

        return models.Listing(
            account_id=account.id,
            platform_listing_id=goods_id,
            title=title[:200],
            status=status,
            price_per_hour=price,
            game_name=game_name[:100],
            account_identifier=str(account_identifier),
            platform_url=f"https://www.mimaapp.com/goods/{goods_id}",
            extra_data=json.dumps(item, ensure_ascii=False),
        )

    def sync_orders(self, account, db):
        self._set_token(account)
        orders = []
        try:
            page = 1
            while True:
                resp = self.session.get(
                    f"{self.base_url}/v1/order/list",
                    params={"page": page, "trade_type_id": 3, "order_status": 1, "type": 2, "size": 50},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"密马订单API错误: {data.get('msg')}")
                    break
                order_list = data.get("data", {}).get("list", []) or []
                if not order_list:
                    break
                for item in order_list:
                    order = self._parse_order(item, account, db)
                    if order:
                        orders.append(order)
                total = data.get("data", {}).get("total", 0)
                if page * 50 >= total or len(order_list) < 50:
                    break
                page += 1
        except Exception as e:
            logger.error(f"密马同步订单失败: {e}")

        if orders:
            existing = {o.platform_order_id: o for o in db.query(models.Order).filter(
                models.Order.account_id == account.id).all()}
            for order in orders:
                if order.platform_order_id not in existing:
                    db.add(order)
            db.commit()
        return orders

    def _parse_order(self, item, account, db):
        order_id = str(item.get("order_id") or item.get("id") or "")
        if not order_id:
            return None
        # 订单状态: 3=进行中, 4=已完成, 6=已取消
        status_val = item.get("order_status", 0)
        if status_val == 3:
            status = "ongoing"
        elif status_val == 4:
            status = "completed"
        elif status_val == 6:
            status = "cancelled"
        else:
            status = "pending"
        amount = float(item.get("seller_income") or item.get("amount") or 0)
        original_amount = float(item.get("total_amount") or item.get("original_amount") or amount)
        duration = float(item.get("duration") or item.get("rental_hours") or 0)
        start_time = None
        end_time = None
        try:
            if item.get("start_time"):
                start_time = datetime.strptime(str(item["start_time"])[:16], "%Y-%m-%d %H:%M")
            if item.get("end_time"):
                end_time = datetime.strptime(str(item["end_time"])[:16], "%Y-%m-%d %H:%M")
        except Exception:
            pass

        # 查找关联商品
        listing_id = None
        goods_id = item.get("goods_id")
        if goods_id:
            listing = db.query(models.Listing).filter(
                models.Listing.account_id == account.id,
                models.Listing.platform_listing_id == str(goods_id)).first()
            if listing:
                listing_id = listing.id

        return models.Order(
            account_id=account.id,
            listing_id=listing_id,
            platform_order_id=order_id,
            order_type="rental",
            buyer_nickname=str(item.get("buyer_nickname") or item.get("buyer_name") or "")[:100],
            listing_title=str(item.get("goods_name") or item.get("title") or "")[:200],
            duration_hours=duration,
            amount=amount,
            original_amount=original_amount,
            status=status,
            start_time=start_time,
            end_time=end_time,
            platform_data=json.dumps(item, ensure_ascii=False),
        )

    def onshelf_listing(self, account, listing, db):
        self._set_token(account)
        try:
            resp = self.session.get(
                f"{self.base_url}/v4/goods/merchant_set_shelf",
                params={"goods_id": listing.platform_listing_id, "action": 1},
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0:
                listing.status = "on_shelf"
                db.commit()
                return {"success": True, "message": "上架成功"}
            return {"success": False, "message": data.get("msg", "上架失败")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def offshelf_listing(self, account, listing, db):
        self._set_token(account)
        try:
            resp = self.session.get(
                f"{self.base_url}/v4/goods/merchant_set_shelf",
                params={"goods_id": listing.platform_listing_id, "action": 2},
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0:
                listing.status = "off_shelf"
                db.commit()
                return {"success": True, "message": "下架成功"}
            return {"success": False, "message": data.get("msg", "下架失败")}
        except Exception as e:
            return {"success": False, "message": str(e)}
