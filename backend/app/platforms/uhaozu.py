"""
U号租平台适配器
API: 商品列表POST /goods/usercenter/list
认证: Cookie(含JSESSIONID)
域名: www.uhaozu.com
"""
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
import json, logging, re
from datetime import datetime
from .base import BasePlatformAdapter
from .. import models

logger = logging.getLogger(__name__)


class UHaoZuAdapter(BasePlatformAdapter):
    platform_key = "uhaozu"
    platform_name = "U号租"
    base_url = "https://www.uhaozu.com"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": "https://www.uhaozu.com/",
            "Origin": "https://www.uhaozu.com",
            "Content-Type": "application/json; charset=utf-8",
        })

    def _load_cookies(self, account):
        super()._load_cookies(account)

    def login(self, account, captcha=None):
        return {"success": False, "message": "U号租登录需要验证码，请使用导入Cookie方式", "need_cookie": True}

    def sync_listings(self, account, db):
        self._load_cookies(account)
        listings = []
        try:
            page = 1
            while True:
                resp = self.session.post(
                    f"{self.base_url}/goods/usercenter/list",
                    json={"page": page, "pageSize": 50, "isViewAuthStatus": True},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                # U号租实际返回格式: {"success":true,"totalCount":15,"object":[...]}
                goods_list = data.get("object", []) or data.get("data", {}).get("list", []) or data.get("list", [])
                if not goods_list:
                    break
                for item in goods_list:
                    listing = self._parse_goods_json(item, account)
                    if listing:
                        listings.append(listing)
                total = data.get("totalCount", 0) or data.get("data", {}).get("total", 0) or data.get("total", 0)
                if page * 50 >= total or len(goods_list) < 50:
                    break
                page += 1
        except Exception as e:
            logger.error(f"U号租同步商品失败: {e}")

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

    def _parse_goods_json(self, item, account):
        goods_id = str(item.get("goodsId") or item.get("id") or "")
        if not goods_id:
            return None
        title = item.get("goodsTitle") or item.get("title", "未知商品")
        game_name = item.get("gameName", "")
        # 租金单位是分
        rental_price = item.get("rentalByHour") or item.get("price") or 0
        try:
            price = round(float(rental_price) / 100, 2)
        except (ValueError, TypeError):
            price = 0
        # 状态: goodsStatus 3=上架中, 4=已下架; rentStatus 0=出租中
        goods_status = item.get("goodsStatus", 0)
        rent_status = item.get("rentStatus", 1)
        if rent_status == 0:
            status = "rented"
        elif goods_status == 3:
            status = "on_shelf"
        else:
            status = "off_shelf"
        # 账号标识
        account_identifier = item.get("gameAccount") or item.get("account") or item.get("qq") or ""
        if not account_identifier:
            account_identifier = goods_id

        return models.Listing(
            account_id=account.id,
            platform_listing_id=goods_id,
            title=title[:200],
            status=status,
            price_per_hour=price,
            game_name=game_name[:100],
            account_identifier=str(account_identifier),
            platform_url=f"https://www.uhaozu.com/goods/{goods_id}",
            extra_data=json.dumps(item, ensure_ascii=False),
        )

    def sync_orders(self, account, db):
        # U号租订单API调用返回9998，暂不自动同步
        logger.info("U号租订单自动同步暂未实现")
        return []

    def onshelf_listing(self, account, listing, db):
        return {"success": False, "message": "U号租上下架功能待开发"}

    def offshelf_listing(self, account, listing, db):
        return {"success": False, "message": "U号租上下架功能待开发"}

    def check_account_status(self, account, db):
        self._load_cookies(account)
        try:
            resp = self.session.get(f"{self.base_url}/usercenter", timeout=10, allow_redirects=False)
            if resp.status_code == 200:
                return "online"
            return "offline"
        except Exception:
            return "offline"
