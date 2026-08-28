"""GitHub OAuth identity exchange and pinning."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


@dataclass(frozen=True)
class GitHubIdentity:
    login: str
    user_id: int


class GitHubOAuth:
    authorize_endpoint = "https://github.com/login/oauth/authorize"
    token_endpoint = "https://github.com/login/oauth/access_token"
    user_endpoint = "https://api.github.com/user"

    def __init__(self, client_id: str, client_secret: str, callback_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.callback_url = callback_url

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.callback_url,
                "state": state,
            }
        )
        return f"{self.authorize_endpoint}?{query}"

    async def exchange_identity(self, code: str) -> GitHubIdentity:
        headers = {"Accept": "application/json", "User-Agent": "im-an-old-sun-box-mcp"}
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            token_response = await client.post(
                self.token_endpoint,
                headers=headers,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.callback_url,
                },
            )
            token_response.raise_for_status()
            token = token_response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise RuntimeError("GitHub did not return an access token")
            user_response = await client.get(
                self.user_endpoint,
                headers={**headers, "Authorization": f"Bearer {token}"},
            )
            user_response.raise_for_status()
            user = user_response.json()
        login = user.get("login")
        user_id = user.get("id")
        if not isinstance(login, str) or not isinstance(user_id, int):
            raise RuntimeError("GitHub returned an invalid identity")
        return GitHubIdentity(login=login, user_id=user_id)


def identity_allowed(identity: GitHubIdentity, *, login: str, user_id: int) -> bool:
    return identity.login.casefold() == login.casefold() and identity.user_id == user_id
