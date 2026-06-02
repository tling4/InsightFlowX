from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from app.schemas.workflow import WorkflowConfig
from app.schemas.competitor import CompetitorInfo, SearchResult
from app.schemas.common import ErrorRecord, CompressedSummary
from app.schemas.feature import FeatureMatrix
from app.schemas.pricing import PricingComparison
from app.schemas.sentiment import UserSentimentAnalysis
from app.schemas.swot import SWOTAnalysis
from app.schemas.report import ReportOutput
from app.schemas.review import ReviewOutput


class WorkflowState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    config: WorkflowConfig
    competitors: list[CompetitorInfo]
    raw_data: dict[str, list[SearchResult]]
    collection_errors: dict[str, str]
    context_summaries: dict[str, str]
    feature_matrix: Optional[FeatureMatrix]
    pricing_comparison: Optional[PricingComparison]
    user_sentiment: Optional[UserSentimentAnalysis]
    swot: Optional[SWOTAnalysis]
    report: Optional[ReportOutput]
    review_result: Optional[ReviewOutput]
    revision_count: int
    max_revisions: int
    current_phase: str
    workflow_status: str
    errors: list[ErrorRecord]
    human_decision: dict
    cached_review_result: Optional[dict]
    review_reroute_target: Optional[str]
    review_result_consumed: bool
