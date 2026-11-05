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
    STARTER = "starter"  # $19/mo — 200 findings, 5 sites
    PRO = "pro"  # $59/mo — 1000 findings, 25 sites
    BUSINESS = "business"  # $199/mo — 5000 findings, 100 sites


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
    finding_limit: int  # находок в месяц; Free — 5 на всё время
    site_limit: int  # 1, 5, 25, 100
    features: set[str] = field(default_factory=set)

    # Предустановленные планы — соответствуют ECONOMICS.md
    @classmethod
    def registry(cls) -> dict[PlanName, Plan]:
        return {
            PlanName.FREE: Plan(
                PlanName.FREE, 0, 5, 1, {"weekly_scan", "email_alert"}
            ),
            PlanName.STARTER: Plan(
                PlanName.STARTER, 1900, 200, 5,
                {"weekly_scan", "email_alert", "telegram_alert", "diff_history"},
            ),
            PlanName.PRO: Plan(
                PlanName.PRO, 5900, 1000, 25,
                {"weekly_scan", "branded_report", "api_access", "priority_queue"},
            ),
            PlanName.BUSINESS: Plan(
                PlanName.BUSINESS, 19900, 5000, 100,
                {"api_access", "white_label", "priority_queue", "custom_domain"},
            ),
        }


@dataclass
class Subscription:
    """Подписка привязана к организации: лимит находок — на аккаунт."""

    organization_id: int
    plan: PlanName
    status: SubscriptionStatus = SubscriptionStatus.TRIAL
    findings_used: int = 0
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
    organization_id: int
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
    organization_id INTEGER PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'trial',
    findings_used INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    trial_ends_at TEXT,
    current_period_ends_at TEXT,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    payment_method TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'draft',
    stripe_invoice_id TEXT,
    due_at TEXT,
    paid_at TEXT,
    pdf_url TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_org ON subscriptions(organization_id);
CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
"""
