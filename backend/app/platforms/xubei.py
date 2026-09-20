"""
虚贝平台适配器
API: https://user-server.xubei.com
认证: Cookie
商品列表: GET /saller/getGoodsManage
商品详情: GET /usercenter/getGoodsDetail (获取完整QQ号)
订单列表: GET /saller/myRentOrderList
上下架: GET /saller/upOrDownGoodsV2?goodsIds=xxx&type=0
"""
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
import json, logging, re
from datetime import datetime
from .base import BasePlatformAdapter
from .. import models

logger = logging.getLogger(__name__)


class XuBeiAdapter(BasePlatformAdapter):
    platform_key = "xubei"
    platform_name = "虚贝"
    base_url = "https://user-server.xubei.com"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": "https://www.xubei.com/",
            "Origin": "https://www.xubei.com",
        })

    def _load_cookies(self, account):
        # 虚贝保存的cookie可能是字符串格式，需要解析
        if account.cookie_data:
            try:
                cookie_json = json.loads(account.cookie_data)
                if isinstance(cookie_json, dict):
                    self.session.cookies.update(cookie_json)
                elif isinstance(cookie_json, list):
                    for c in cookie_json:
                        if isinstance(c, dict) and "name" in c and "value" in c:
                            self.session.cookies.set(c["name"], c["value"])
            except json.JSONDecodeError:
                # 字符串格式: name1=value1; name2=value2
                try:
                    for pair in account.cookie_data.split(";"):
                        if "=" in pair:
                            name, value = pair.strip().split("=", 1)
                            self.session.cookies.set(name.strip(), value.strip())
                except Exception:
                    pass

    def login(self, account, captcha=None):
        return {"success": False, "message": "虚贝登录需要验证码，请使用导入Cookie方式", "need_cookie": True}

    def sync_listings(self, account, db):
        self._load_cookies(account)
        listings = []
        try:
            page = 1
            while True:
                resp = self.session.get(
                    f"{self.base_url}/saller/getGoodsManage",
                    params={"tradingWay": 1, "pcFlag": 1, "sellerLimitGoodsFlag": 1,
                            "pageIndex": page, "pageSize": 50, "goodsStatus": 1},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                goods_list = data.get("data", {}).get("list", []) or data.get("list", []) or []
                if not goods_list:
                    break
                for item in goods_list:
                    listing = self._parse_goods(item, account)
                    if listing:
                        listings.append(listing)
                total = data.get("data", {}).get("total", 0) or data.get("total", 0)
                if page * 50 >= total or len(goods_list) < 50:
                    break
                page += 1
        except Exception as e:
            logger.error(f"虚贝同步商品失败: {e}")

        # 获取完整QQ号（商品列表的gameAccount是脱敏的）
        for listing in listings:
            try:
                detail = self._get_goods_detail(listing.platform_listing_id)
                if detail:
                    full_account = detail.get("gameAccount") or detail.get("account") or ""
                    if full_account and "***" not in full_account:
                        listing.account_identifier = full_account
            except Exception:
                pass

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

    def _get_goods_detail(self, goods_id):
        try:
            resp = self.session.get(
                f"{self.base_url}/usercenter/getGoodsDetail",
                params={"goodsId": goods_id},
                timeout=10
            )
            data = resp.json()
            return data.get("data", {}) or {}
        except Exception:
            return {}

    def _parse_goods(self, item, account):
        goods_id = str(item.get("goodsId") or item.get("id") or item.get("goods_id") or "")
        if not goods_id:
            return None
        title = item.get("goodsName") or item.get("title", "未知商品")
        game_name = item.get("gameName", "")
        price = float(item.get("rentalPrice") or item.get("price") or 0)
        # 状态: goodsStatus 1=可租赁(上架中), 3=仓库中(已下架)
        goods_status = item.get("goodsStatus", 0)
        if goods_status == 1:
            status = "on_shelf"
        else:
            status = "off_shelf"
        # 账号标识（列表中是脱敏的，后面用详情API补全）
        account_identifier = item.get("gameAccount") or item.get("account") or goods_id

        return models.Listing(
            account_id=account.id,
            platform_listing_id=goods_id,
            title=title[:200],
            status=status,
            price_per_hour=price,
            game_name=game_name[:100],
            account_identifier=str(account_identifier),
            platform_url=f"https://www.xubei.com/goods/{goods_id}",
            extra_data=json.dumps(item, ensure_ascii=False),
        )

    def sync_orders(self, account, db):
        self._load_cookies(account)
        orders = []
        try:
            page = 1
            while True:
                resp = self.session.get(
                    f"{self.base_url}/saller/myRentOrderList",
                    params={"pageIndex": page, "pageSize": 50},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                order_list = data.get("data", {}).get("list", []) or data.get("list", []) or []
                if not order_list:
                    break
                for item in order_list:
                    order = self._parse_order(item, account, db)
                    if order:
                        orders.append(order)
                total = data.get("data", {}).get("total", 0) or data.get("total", 0)
                if page * 50 >= total or len(order_list) < 50:
                    break
                page += 1
        except Exception as e:
            logger.error(f"虚贝同步订单失败: {e}")

        if orders:
            existing = {o.platform_order_id: o for o in db.query(models.Order).filter(
                models.Order.account_id == account.id).all()}
            for order in orders:
                if order.platform_order_id not in existing:
                    db.add(order)
            db.commit()
        return orders

    def _parse_order(self, item, account, db):
        order_id = str(item.get("orderId") or item.get("id") or item.get("order_id") or "")
        if not order_id:
            return None
        # 状态: orderStatus=100或isFinished=1 → completed
        order_status = item.get("orderStatus", 0)
        is_finished = item.get("isFinished", 0)
        if order_status == 100 or is_finished == 1:
            status = "completed"
        elif order_status in (1, 2, 3):
            status = "ongoing"
        else:
            status = "pending"
        amount = float(item.get("sellerIncome") or item.get("amount") or item.get("totalAmount") or 0)
        duration = float(item.get("rentalHours") or item.get("duration") or 0)
        start_time = None
        end_time = None
        try:
            if item.get("startTime"):
                start_time = datetime.strptime(str(item["startTime"])[:19], "%Y-%m-%d %H:%M:%S")
            if item.get("endTime"):
                end_time = datetime.strptime(str(item["endTime"])[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        listing_id = None
        goods_id = item.get("goodsId") or item.get("goods_id")
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
            buyer_nickname=str(item.get("buyerNickname") or item.get("buyerName") or "")[:100],
            listing_title=str(item.get("goodsName") or item.get("title") or "")[:200],
            duration_hours=duration,
            amount=amount,
            original_amount=amount,
            status=status,
            start_time=start_time,
            end_time=end_time,
            platform_data=json.dumps(item, ensure_ascii=False),
        )

    def onshelf_listing(self, account, listing, db):
        self._load_cookies(account)
        try:
            resp = self.session.get(
                f"{self.base_url}/saller/upOrDownGoodsV2",
                params={"goodsIds": listing.platform_listing_id, "type": 0},
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0 or data.get("success"):
                listing.status = "on_shelf"
                db.commit()
                return {"success": True, "message": "上架成功"}
            return {"success": False, "message": data.get("msg", "上架失败")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def offshelf_listing(self, account, listing, db):
        self._load_cookies(account)
        try:
            resp = self.session.get(
                f"{self.base_url}/saller/upOrDownGoodsV2",
                params={"goodsIds": listing.platform_listing_id, "type": 1},
                timeout=15
            )
            data = resp.json()
            if data.get("code") == 0 or data.get("success"):
                listing.status = "off_shelf"
                db.commit()
                return {"success": True, "message": "下架成功"}
            return {"success": False, "message": data.get("msg", "下架失败")}
        except Exception as e:
            return {"success": False, "message": str(e)}
