"""Stripe integration for pay-per-scan billing.

Handles: Checkout Sessions, Webhooks, Customer/Subscription management.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import stripe

LOGGER = logging.getLogger("webscope.stripe")


@dataclass
class StripeConfig:
    """Stripe configuration from environment."""
    secret_key: str | None = None
    publishable_key: str | None = None
    webhook_secret: str | None = None
    price_ids: dict[str, str] = None  # plan_name -> price_id

    def __post_init__(self):
        if self.price_ids is None:
            self.price_ids = {
                "starter": os.environ.get("STRIPE_PRICE_STARTER"),
                "pro": os.environ.get("STRIPE_PRICE_PRO"),
                "agency": os.environ.get("STRIPE_PRICE_AGENCY"),
            }

    @property
    def is_configured(self) -> bool:
        return bool(self.secret_key and self.publishable_key)

    @classmethod
    def from_env(cls) -> StripeConfig:
        return cls(
            secret_key=os.environ.get("STRIPE_SECRET_KEY"),
            publishable_key=os.environ.get("STRIPE_PUBLISHABLE_KEY"),
            webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET"),
        )


class StripeClient:
    """Wrapper around Stripe API for webscope billing."""

    def __init__(self, config: StripeConfig | None = None):
        self.config = config or StripeConfig.from_env()
        if self.config.secret_key:
            stripe.api_key = self.config.secret_key

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    def create_customer(self, email: str, name: str | None = None, metadata: dict | None = None) -> stripe.Customer | None:
        """Create a Stripe customer."""
        if not self.is_configured:
            LOGGER.warning("Stripe not configured, cannot create customer")
            return None
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata=metadata or {},
            )
            LOGGER.info("Created Stripe customer %s for %s", customer.id, email)
            return customer
        except stripe.error.StripeError as e:
            LOGGER.error("Failed to create Stripe customer: %s", e)
            return None

    def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        mode: str = "subscription",
        metadata: dict | None = None,
    ) -> stripe.checkout.Session | None:
        """Create a Stripe Checkout Session for subscription or one-time payment."""
        if not self.is_configured:
            LOGGER.warning("Stripe not configured, cannot create checkout session")
            return None
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode=mode,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata or {},
                allow_promotion_codes=True,
            )
            LOGGER.info("Created Stripe checkout session %s for customer %s", session.id, customer_id)
            return session
        except stripe.error.StripeError as e:
            LOGGER.error("Failed to create checkout session: %s", e)
            return None

    def create_portal_session(self, customer_id: str, return_url: str) -> stripe.billing_portal.Session | None:
        """Create a Stripe Billing Portal session for customer self-service."""
        if not self.is_configured:
            LOGGER.warning("Stripe not configured, cannot create portal session")
            return None
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            LOGGER.info("Created Stripe portal session for customer %s", customer_id)
            return session
        except stripe.error.StripeError as e:
            LOGGER.error("Failed to create portal session: %s", e)
            return None

    def get_subscription(self, subscription_id: str) -> stripe.Subscription | None:
        """Retrieve a subscription by ID."""
        if not self.is_configured:
            return None
        try:
            return stripe.Subscription.retrieve(subscription_id)
        except stripe.error.StripeError as e:
            LOGGER.error("Failed to retrieve subscription %s: %s", subscription_id, e)
            return None

    def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> bool:
        """Cancel a subscription."""
        if not self.is_configured:
            return False
        try:
            stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=at_period_end,
            )
            LOGGER.info("Scheduled subscription %s for cancellation at period end: %s", subscription_id, at_period_end)
            return True
        except stripe.error.StripeError as e:
            LOGGER.error("Failed to cancel subscription %s: %s", subscription_id, e)
            return False

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> stripe.Event | None:
        """Verify and construct webhook event."""
        if not self.config.webhook_secret:
            LOGGER.warning("Stripe webhook secret not configured")
            return None
        try:
            return stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=self.config.webhook_secret,
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            LOGGER.warning("Webhook signature verification failed: %s", e)
            return None


# Global instance
_stripe_client: StripeClient | None = None


def get_stripe_client() -> StripeClient:
    """Get or create global Stripe client."""
    global _stripe_client
    if _stripe_client is None:
        _stripe_client = StripeClient()
    return _stripe_client


def init_stripe(config: StripeConfig | None = None) -> StripeClient:
    """Initialize global Stripe client with config."""
    global _stripe_client
    _stripe_client = StripeClient(config)
    return _stripe_client


# Webhook event handlers
async def handle_checkout_session_completed(event: stripe.Event, storage) -> None:
    """Handle successful checkout session."""
    session = event.data.object
    customer_id = session.customer
    subscription_id = session.subscription
    metadata = session.metadata or {}

    organization_id = metadata.get("organization_id")
    package_type = metadata.get("package_type")
    if not organization_id:
        LOGGER.warning("No organization_id in checkout session metadata")
        return

    # Create scan package for the organization
    packages_config = {
        "starter": {"scans": 10, "price_cents": 2900},
        "pro": {"scans": 50, "price_cents": 9900},
        "agency": {"scans": 100, "price_cents": 17900},
    }
    if package_type in packages_config:
        config = packages_config[package_type]
        pkg = storage.create_scan_package(
            organization_id=int(organization_id),
            scans_total=config["scans"],
            price_cents=config["price_cents"],
            currency="USD",
        )
        LOGGER.info("Created scan package %s for org %s via Stripe checkout", pkg.id, organization_id)
    else:
        LOGGER.warning("Unknown package_type %s in checkout metadata", package_type)


async def handle_subscription_updated(event: stripe.Event, storage) -> None:
    """Handle subscription status change."""
    subscription = event.data.object
    customer_id = subscription.customer
    status = subscription.status

    # TODO: Update organization subscription status in storage
    LOGGER.info("Subscription %s for customer %s status: %s", subscription.id, customer_id, status)


async def handle_invoice_paid(event: stripe.Event, storage) -> None:
    """Handle successful invoice payment."""
    invoice = event.data.object
    LOGGER.info("Invoice %s paid for customer %s", invoice.id, invoice.customer)


async def handle_payment_failed(event: stripe.Event, storage) -> None:
    """Handle failed payment."""
    invoice = event.data.object
    LOGGER.warning("Payment failed for invoice %s, customer %s", invoice.id, invoice.customer)


# Event type to handler mapping
WEBHOOK_HANDLERS = {
    "checkout.session.completed": handle_checkout_session_completed,
    "customer.subscription.updated": handle_subscription_updated,
    "customer.subscription.deleted": handle_subscription_updated,
    "invoice.paid": handle_invoice_paid,
    "invoice.payment_failed": handle_payment_failed,
}


async def process_stripe_webhook(event: stripe.Event, storage) -> None:
    """Route webhook event to appropriate handler."""
    handler = WEBHOOK_HANDLERS.get(event.type)
    if handler:
        await handler(event, storage)
    else:
        LOGGER.debug("No handler for Stripe event type: %s", event.type)