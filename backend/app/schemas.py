from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserInfo(BaseModel):
    id: int
    username: str
    is_active: bool
    class Config:
        from_attributes = True


class RentalAccountCreate(BaseModel):
    platform: str
    platform_username: str
    platform_password: Optional[str] = None
    nickname: Optional[str] = None
    group_name: str = "默认分组"
    auto_manage: bool = True
    onshelf_start_time: str = "08:00"
    onshelf_end_time: str = "23:00"
    rental_frequency: int = 0


class RentalAccountUpdate(BaseModel):
    nickname: Optional[str] = None
    group_name: Optional[str] = None
    auto_manage: Optional[bool] = None
    onshelf_start_time: Optional[str] = None
    onshelf_end_time: Optional[str] = None
    rental_frequency: Optional[int] = None
    platform_password: Optional[str] = None
    cookie_data: Optional[str] = None
    token_data: Optional[str] = None
    extra_config: Optional[dict] = None


class RentalAccountResponse(BaseModel):
    id: int
    platform: str
    platform_username: str
    nickname: Optional[str]
    group_name: str
    status: str
    auto_manage: bool
    onshelf_start_time: str
    onshelf_end_time: str
    rental_frequency: int
    last_sync_time: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True


class AccountLoginRequest(BaseModel):
    captcha: Optional[str] = None


class ListingResponse(BaseModel):
    id: int
    account_id: int
    platform_listing_id: Optional[str]
    title: str
    game_name: Optional[str]
    price_per_hour: float
    price_per_day: float
    status: str
    total_rentals: int
    rating: float
    account_identifier: Optional[str] = None
    remark: Optional[str] = None
    updated_at: datetime
    class Config:
        from_attributes = True


class ListingUpdate(BaseModel):
    remark: Optional[str] = None
    account_identifier: Optional[str] = None
    status: Optional[str] = None


class ListingActionRequest(BaseModel):
    action: str = Field(description="onshelf=上架, offshelf=下架, refresh=刷新")


class OrderResponse(BaseModel):
    id: int
    account_id: int
    platform_order_id: str
    order_type: str
    buyer_nickname: Optional[str]
    listing_title: Optional[str]
    duration_hours: float
    amount: float
    status: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    is_flagged: bool
    flag_reason: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True


class StatsOverview(BaseModel):
    today_income: float
    today_orders: int
    today_hours: float
    week_income: float
    week_orders: int
    month_income: float
    month_orders: int
    total_accounts: int
    online_accounts: int
    total_listings: int
    on_shelf_listings: int
    total_game_accounts: int = 0


class DailyStatResponse(BaseModel):
    date: str
    total_orders: int
    total_income: float
    total_hours: float
    abnormal_orders: int
    class Config:
        from_attributes = True


class PlatformInfo(BaseModel):
    key: str
    name: str
    icon: str
    supported: bool
    description: str
