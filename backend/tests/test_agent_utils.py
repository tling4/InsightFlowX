from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import agent_utils
from app.agents.agent_utils import _normalize_schema_payload
from app.schemas.feature import FeatureMatrix
from app.schemas.gtm import GTMAnalysis


def _feature_payload():
    return {
        "dimensions": ["手续费策略"],
        "matrix": [
            {
                "feature_name": "提现手续费",
                "products": {"支付宝": "有免费额度"},
            }
        ],
    }


def test_normalize_schema_payload_unwraps_singleton_list_wrapper():
    payload = _feature_payload()

    normalized = _normalize_schema_payload({"feature_matrix": [payload]}, FeatureMatrix)

    assert FeatureMatrix.model_validate(normalized).dimensions == ["手续费策略"]


def test_normalize_schema_payload_keeps_multi_item_list_wrapper_invalid():
    payload = _feature_payload()
    wrapped = {"FeatureMatrix": [payload, payload]}

    assert _normalize_schema_payload(wrapped, FeatureMatrix) == wrapped


def test_feature_matrix_accepts_common_llm_field_aliases_and_url_refs():
    matrix = FeatureMatrix.model_validate({
        "dimensions": ["手续费策略"],
        "matrix": [{
            "dimension": "提现手续费",
            "comparisons": [{
                "product": "支付宝",
                "support_level": "supported",
                "difference_summary": "免费提现额度之外的金额按照公开规则收取服务费。",
                "evidence_refs": ["https://example.com/alipay-fee"],
            }],
        }],
    })

    assert matrix.matrix[0].feature_name == "提现手续费"
    assert matrix.matrix[0].comparisons[0].evidence_refs[0].url == "https://example.com/alipay-fee"


def test_gtm_analysis_accepts_url_only_evidence_refs():
    gtm = GTMAnalysis.model_validate({
        "launch_rhythm": {
            "summary": "通过公开发布节奏逐步扩展。",
            "evidence_refs": ["https://example.com/launch"],
        },
    })

    assert gtm.launch_rhythm.evidence_refs[0].url == "https://example.com/launch"


@pytest.mark.asyncio
async def test_invoke_json_model_normalizes_evidence_refs_without_repair(monkeypatch):
    llm = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="""{
            "launch_rhythm": {
                "summary": "通过公开发布节奏逐步扩展。",
                "evidence_refs": ["https://example.com/launch"],
                "confidence": 0.7
            },
            "summary": "增长节奏明确。"
        }""")),
    )
    monkeypatch.setattr(agent_utils, "make_chat_model", lambda: llm)

    result = await agent_utils.invoke_json_model("system", {}, GTMAnalysis)

    assert result.launch_rhythm.evidence_refs[0].url == "https://example.com/launch"
    assert llm.ainvoke.await_count == 1
