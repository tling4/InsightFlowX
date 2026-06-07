import pytest

from app.services.interview_service import EMPTY_RESPONSE_FALLBACK, _collect_interview_response


class FakeInterviewAgent:
    def __init__(self, responses: list[list[str]]):
        self.responses = responses
        self.calls = 0

    async def stream_response(self, _messages):
        response = self.responses[self.calls]
        self.calls += 1
        for chunk in response:
            yield chunk


@pytest.mark.asyncio
async def test_collect_interview_response_retries_empty_response():
    agent = FakeInterviewAgent([[], ["有效", "回复"]])

    response = await _collect_interview_response([], lambda: agent)

    assert response == "有效回复"
    assert agent.calls == 2


@pytest.mark.asyncio
async def test_collect_interview_response_falls_back_after_two_empty_responses():
    agent = FakeInterviewAgent([[], []])

    response = await _collect_interview_response([], lambda: agent)

    assert response == EMPTY_RESPONSE_FALLBACK
    assert agent.calls == 2
