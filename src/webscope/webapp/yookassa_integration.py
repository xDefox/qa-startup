"""ЮKassa integration for pay-per-scan billing (Russian market).

Handles: Payment creation, Webhooks, Refunds, Payouts.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

import httpx

LOGGER = logging.getLogger("webscope.yookassa")


@dataclass
class YookassaConfig:
    """ЮKassa configuration from environment."""

    shop_id: str | None = None
    secret_key: str | None = None
    webhook_secret: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.shop_id and self.secret_key)

    @classmethod
    def from_env(cls) -> YookassaConfig:
        return cls(
            shop_id=os.environ.get("YOOKASSA_SHOP_ID"),
            secret_key=os.environ.get("YOOKASSA_SECRET_KEY"),
            webhook_secret=os.environ.get("YOOKASSA_WEBHOOK_SECRET"),
        )


class YookassaClient:
    """Wrapper around ЮKassa API for webscope billing."""

    BASE_URL = "https://api.yookassa.ru/v3"

    def __init__(self, config: YookassaConfig | None = None):
        self.config = config or YookassaConfig.from_env()
        self._client = (
            httpx.AsyncClient(
                auth=(self.config.shop_id, self.config.secret_key),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": str(uuid.uuid4()),
                },
                timeout=30.0,
            )
            if self.config.is_configured
            else None
        )

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    async def close(self):
        if self._client:
            await self._client.aclose()

    async def create_payment(
        self,
        amount_cents: int,
        currency: str = "RUB",
        description: str = "",
        return_url: str = "",
        metadata: dict | None = None,
        capture: bool = True,
        save_payment_method: bool = False,
    ) -> dict | None:
        """Create a payment (redirects user to ЮKassa payment page)."""
        if not self.is_configured:
            LOGGER.warning("ЮKassa not configured, cannot create payment")
            return None

        payload = {
            "amount": {
                "value": f"{amount_cents / 100:.2f}",
                "currency": currency,
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "capture": capture,
            "description": description[:128],
            "metadata": metadata or {},
        }

        if save_payment_method:
            payload["save_payment_method"] = True

        try:
            response = await self._client.post("/payments", json=payload)
            response.raise_for_status()
            payment = response.json()
            LOGGER.info(
                "Created ЮKassa payment %s for %d %s",
                payment["id"],
                payment["amount"]["value"],
                payment["amount"]["currency"],
            )
            return payment
        except httpx.HTTPError as e:
            LOGGER.error("Failed to create ЮKassa payment: %s", e)
            return None

    async def get_payment(self, payment_id: str) -> dict | None:
        """Retrieve payment by ID."""
        if not self.is_configured:
            return None
        try:
            response = await self._client.get(f"/payments/{payment_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            LOGGER.error("Failed to retrieve payment %s: %s", payment_id, e)
            return None

    async def cancel_payment(self, payment_id: str) -> dict | None:
        """Cancel a pending payment."""
        if not self.is_configured:
            return None
        try:
            response = await self._client.post(f"/payments/{payment_id}/cancel")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            LOGGER.error("Failed to cancel payment %s: %s", payment_id, e)
            return None

    async def create_refund(self, payment_id: str, amount_cents: int | None = None) -> dict | None:
        """Create a refund for a payment."""
        if not self.is_configured:
            return None
        payload = {"payment_id": payment_id}
        if amount_cents:
            payload["amount"] = {"value": f"{amount_cents / 100:.2f}", "currency": "RUB"}
        try:
            response = await self._client.post("/refunds", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            LOGGER.error("Failed to create refund for payment %s: %s", payment_id, e)
            return None

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify webhook signature (SHA256 HMAC with secret)."""
        import hashlib
        import hmac

        if not self.config.webhook_secret:
            return False
        expected = hmac.new(
            self.config.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature, expected)


# Global instance
_yookassa_client: YookassaClient | None = None


async def get_yookassa_client() -> YookassaClient:
    """Get or create global ЮKassa client."""
    global _yookassa_client
    if _yookassa_client is None:
        _yookassa_client = YookassaClient()
    return _yookassa_client


async def init_yookassa(config: YookassaConfig | None = None) -> YookassaClient:
    """Initialize global ЮKassa client with config."""
    global _yookassa_client
    _yookassa_client = YookassaClient(config)
    return _yookassa_client


async def process_yookassa_webhook(event_type: str, payload: dict, storage) -> None:
    """Route webhook event to appropriate handler."""
    if event_type == "payment.succeeded":
        await handle_payment_succeeded(payload, storage)
    elif event_type == "payment.canceled":
        await handle_payment_canceled(payload, storage)
    elif event_type == "refund.succeeded":
        await handle_refund_succeeded(payload, storage)
    else:
        LOGGER.debug("No handler for ЮKassa event type: %s", event_type)


async def handle_payment_succeeded(payload: dict, storage) -> None:
    """Handle successful payment."""
    payment = payload.get("object", {})
    payment_id = payment.get("id")
    metadata = payment.get("metadata", {})
    organization_id = metadata.get("organization_id")
    package_type = metadata.get("package_type")

    if not organization_id:
        LOGGER.warning("No organization_id in payment metadata for payment %s", payment_id)
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
            currency="RUB",
        )
        LOGGER.info("Created scan package %s for org %s via ЮKassa payment", pkg.id, organization_id)
    else:
        LOGGER.warning("Unknown package_type %s in payment metadata", package_type)


async def handle_payment_canceled(payload: dict, storage) -> None:
    """Handle canceled payment."""
    payment = payload.get("object", {})
    payment_id = payment.get("id")
    LOGGER.info("Payment canceled: %s", payment_id)


async def handle_refund_succeeded(payload: dict, storage) -> None:
    """Handle successful refund."""
    refund = payload.get("object", {})
    refund_id = refund.get("id")
    payment_id = refund.get("payment_id")
    LOGGER.info("Refund %s succeeded for payment %s", refund_id, payment_id)
