"""Pydantic v2 schemas for tenant chat analytics and unanswered questions."""

from pydantic import BaseModel


class DailyMessageCount(BaseModel):
    """Message count aggregated for a single UTC calendar date."""

    date: str
    customer_messages: int
    bot_messages: int
    agent_messages: int


class TopUnansweredQuestion(BaseModel):
    """Frequently occurring question that required human handoff."""

    question: str
    count: int


class AnalyticsSummaryResponse(BaseModel):
    """Dashboard analytics summary for a tenant."""

    days: int
    total_conversations: int
    total_customer_messages: int
    total_bot_messages: int
    total_handoffs: int
    auto_resolved_rate: float
    handoff_rate: float
    used_messages_this_month: int
    limit_messages_this_month: int
    messages_per_day: list[DailyMessageCount]
    top_unanswered_questions: list[TopUnansweredQuestion]
