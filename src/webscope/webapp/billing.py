"""Структура биллинга — скелет без полной интеграции Stripe.

Цель: формализовать данные подписки, чтобы Milestone 4 (биллинг) можно было
подключить к существующей БД (sites) без переработки архитектуры.

Не включает: вызовы Stripe API, обработку webhook, налоговую логику.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PlanName(str, Enum):
    FREE = "free"
    SOLO = "solo"  # $12/mo — 1 site, weekly, alerts
    STUDIO = "studio"  # $59/mo — 10 sites, branded report
    AGENCY = "agency"  # $149/mo — 40 sites, API, white-label


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"


@dataclass
class Plan:
    name: PlanName
    price_usd_cents: int
    site_limit: int  # 1, 10, 40; 0 = unlimited
    features: set[str] = field(default_factory=set)

    # Предустановленные планы — соответствуют pitch §11
    @classmethod
    def registry(cls) -> dict[PlanName, Plan]:
        return {
            PlanName.FREE: Plan(PlanName.FREE, 0, 1, {"weekly_scan", "email_alert"}),
            PlanName.SOLO: Plan(
                PlanName.SOLO, 1200, 1, {"weekly_scan", "email_alert", "telegram_alert", "diff_history"}
            ),
            PlanName.STUDIO: Plan(
                PlanName.STUDIO, 5900, 10, {"branded_report", "white_label", "weekly_scan", "api_access"}
            ),
            PlanName.AGENCY: Plan(
                PlanName.AGENCY, 14900, 40, {"api_access", "white_label", "priority_queue", "custom_domain"}
            ),
        }


@dataclass
class Subscription:
    """Подписка привязана к site (per-site pricing)."""

    site_id: int
    plan: PlanName
    status: SubscriptionStatus = SubscriptionStatus.TRIAL
    started_at: str = ""
    trial_ends_at: str | None = None
    current_period_ends_at: str | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    payment_method: str | None = None  # card / bank_transfer / manual_invoice

    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL)


@dataclass
class Invoice:
    subscription_site_id: int
    amount_usd_cents: int
    currency: str = "USD"
    status: str = "draft"  # draft | open | paid | void | uncollectible
    stripe_invoice_id: str | None = None
    due_at: str | None = None
    paid_at: str | None = None
    pdf_url: str | None = None


# ------------------------------------------------------------------ DB-скелет
# Эти SQL-операторы предназначены для добавления в storage.py через миграцию.
BILLING_SCHEMA_ADDON = """
CREATE TABLE IF NOT EXISTS subscriptions (
    site_id INTEGER PRIMARY KEY REFERENCES sites(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'trial',
    started_at TEXT NOT NULL,
    trial_ends_at TEXT,
    current_period_ends_at TEXT,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    payment_method TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'draft',
    stripe_invoice_id TEXT,
    due_at TEXT,
    paid_at TEXT,
    pdf_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_site ON subscriptions(site_id);
CREATE INDEX IF NOT EXISTS idx_invoices_site ON invoices(site_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
"""
