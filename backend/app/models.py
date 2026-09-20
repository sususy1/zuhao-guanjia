from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    accounts = relationship("RentalAccount", back_populates="owner")


class RentalAccount(Base):
    __tablename__ = "rental_accounts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform = Column(String(50), index=True, nullable=False)
    platform_username = Column(String(100), nullable=False)
    platform_password = Column(String(255))
    cookie_data = Column(Text)
    token_data = Column(Text)
    nickname = Column(String(100))
    group_name = Column(String(50), default="默认分组")
    status = Column(String(20), default="offline")
    auto_manage = Column(Boolean, default=True)
    onshelf_start_time = Column(String(10), default="08:00")
    onshelf_end_time = Column(String(10), default="23:00")
    rental_frequency = Column(Integer, default=0)
    last_sync_time = Column(DateTime)
    error_message = Column(Text)
    extra_config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner = relationship("User", back_populates="accounts")
    listings = relationship("Listing", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="account", cascade="all, delete-orphan")


class Listing(Base):
    __tablename__ = "listings"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("rental_accounts.id"), nullable=False)
    platform_listing_id = Column(String(100), index=True)
    title = Column(String(200), nullable=False)
    game_name = Column(String(100))
    price_per_hour = Column(Float, default=0)
    price_per_day = Column(Float, default=0)
    status = Column(String(20), default="off_shelf")
    total_rentals = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    platform_url = Column(String(500))
    account_identifier = Column(String(100), index=True)
    remark = Column(String(500))
    extra_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    account = relationship("RentalAccount", back_populates="listings")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("rental_accounts.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"))
    platform_order_id = Column(String(100), unique=True, index=True)
    order_type = Column(String(20), default="rental")
    buyer_nickname = Column(String(100))
    listing_title = Column(String(200))
    duration_hours = Column(Float, default=0)
    amount = Column(Float, default=0)
    original_amount = Column(Float, default=0)
    platform_fee = Column(Float, default=0)
    status = Column(String(30), default="pending")
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    is_flagged = Column(Boolean, default=False)
    flag_reason = Column(String(200))
    platform_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    account = relationship("RentalAccount", back_populates="orders")


class DailyStat(Base):
    __tablename__ = "daily_stats"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(10), index=True, nullable=False)
    account_id = Column(Integer, ForeignKey("rental_accounts.id"))
    platform = Column(String(50), index=True)
    total_orders = Column(Integer, default=0)
    total_income = Column(Float, default=0)
    total_hours = Column(Float, default=0)
    abnormal_orders = Column(Integer, default=0)
    extra_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaskLog(Base):
    __tablename__ = "task_logs"
    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(50), index=True)
    account_id = Column(Integer, ForeignKey("rental_accounts.id"))
    platform = Column(String(50))
    status = Column(String(20), default="success")
    message = Column(Text)
    detail = Column(JSON, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
