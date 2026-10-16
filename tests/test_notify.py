import requests

from housing.notify import discord


def test_without_a_webhook_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert discord("hello") is False


def test_posts_the_message_truncated_to_discord_limit(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("housing.notify.requests.post", post)
    assert discord("m" * 3000, webhook_url="https://hooks.example/1") is True
    assert calls[0][0] == "https://hooks.example/1"
    assert calls[0][1]["json"] == {"content": "m" * 1900} and calls[0][1]["timeout"] == 10


def test_failed_post_returns_false(monkeypatch):
    def post(url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("housing.notify.requests.post", post)
    assert discord("x", webhook_url="https://hooks.example/1") is False
