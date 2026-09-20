from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
import requests, json, logging
from .. import models

logger = logging.getLogger(__name__)


class BasePlatformAdapter(ABC):
    platform_key: str = ""
    platform_name: str = ""
    base_url: str = ""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def _load_cookies(self, account: models.RentalAccount):
        if account.cookie_data:
            try:
                self.session.cookies.update(json.loads(account.cookie_data))
            except Exception:
                pass

    @abstractmethod
    def login(self, account: models.RentalAccount, captcha: Optional[str] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def sync_listings(self, account: models.RentalAccount, db: Session) -> List[models.Listing]:
        pass

    @abstractmethod
    def sync_orders(self, account: models.RentalAccount, db: Session) -> List[models.Order]:
        pass

    @abstractmethod
    def onshelf_listing(self, account: models.RentalAccount, listing: models.Listing, db: Session) -> Dict[str, Any]:
        pass

    @abstractmethod
    def offshelf_listing(self, account: models.RentalAccount, listing: models.Listing, db: Session) -> Dict[str, Any]:
        pass

    def check_account_status(self, account: models.RentalAccount, db: Session) -> str:
        return "online"
