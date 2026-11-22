"""Subscription plan definitions and monthly quota limits."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanConfig:
    """Typed feature and usage limits for a SaaS subscription tier."""

    name: str
    monthly_messages: int
    max_channels: int
    max_documents: int
    price_thb: int


PLANS: dict[str, PlanConfig] = {
    "trial": PlanConfig(
        name="trial",
        monthly_messages=200,
        max_channels=1,
        max_documents=10,
        price_thb=0,
    ),
    "starter": PlanConfig(
        name="starter",
        monthly_messages=1_000,
        max_channels=1,
        max_documents=20,
        price_thb=990,
    ),
    "pro": PlanConfig(
        name="pro",
        monthly_messages=5_000,
        max_channels=3,
        max_documents=100,
        price_thb=2_490,
    ),
    "business": PlanConfig(
        name="business",
        monthly_messages=20_000,
        max_channels=10,
        max_documents=500,
        price_thb=5_990,
    ),
}


def get_plan_config(plan_name: str) -> PlanConfig:
    """Return the configured limits for `plan_name`, defaulting safely to trial."""
    return PLANS.get(plan_name.lower(), PLANS["trial"])
