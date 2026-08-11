import json

import pytest
import responses

from pr_review_bot.clients.ai import AIAPIError, OmniRouteClient, build_prompt


def test_build_prompt() -> None:
    prompt = build_prompt("Fix bug", "diff line")
    assert "PR Title: Fix bug" in prompt
    assert "```diff\ndiff line\n```" in prompt
    assert "Сделай code review." in prompt


@responses.activate
def test_omniroute_client_review(ai_client: OmniRouteClient) -> None:
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={
            "choices": [
                {"message": {"content": "Great PR!"}}
            ]
        },
        status=200,
    )
    result = ai_client.review("Title", "diff")
    assert result == "Great PR!"
    req = responses.calls[0].request
    body = json.loads(req.body)
    assert body["model"] == "kr/qwen3-code-next"
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 2048
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


@responses.activate
def test_omniroute_client_review_http_error(ai_client: OmniRouteClient) -> None:
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={"error": "rate limited"},
        status=429,
    )
    with pytest.raises(AIAPIError, match="AI backend returned 429"):
        ai_client.review("Title", "diff")


@responses.activate
def test_omniroute_client_review_missing_content(ai_client: OmniRouteClient) -> None:
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={"choices": [{"message": {}}]},
        status=200,
    )
    with pytest.raises(AIAPIError, match="no 'content' field"):
        ai_client.review("Title", "diff")


@responses.activate
def test_omniroute_client_review_empty_choices(ai_client: OmniRouteClient) -> None:
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={"choices": []},
        status=200,
    )
    with pytest.raises(AIAPIError, match="'choices' is empty"):
        ai_client.review("Title", "diff")


@responses.activate
def test_omniroute_client_review_bad_shape(ai_client: OmniRouteClient) -> None:
    responses.add(
        responses.POST,
        "https://omniroute.test/v1/chat/completions",
        json={"unexpected": "shape"},
        status=200,
    )
    with pytest.raises(AIAPIError, match="Unexpected AI response shape"):
        ai_client.review("Title", "diff")
