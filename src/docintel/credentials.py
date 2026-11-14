"""API keys for the hosted model providers: who supplies them and where they live.

DocIntel is "bring your own key" (BYOK) by default:

* Each browser session types in its own key. The key is kept in that session's
  ``st.session_state`` (server memory) inside a :class:`SessionKeyStore`, and it is used only
  for the provider it was entered for.
* Keys in the server environment or ``.env`` are ignored, unless the operator explicitly sets
  ``DOCINTEL_KEY_MODE=owner``. That mode is for the key owner's own local use, or a private
  deployment whose users are authorized to bill the owner's account.
* A key typed into the browser is never copied into ``os.environ``, logs, URLs, files,
  Streamlit's cross-session caches or error messages.

Only the provider adapters read a key value, through ``Credential.secret.get_secret_value()``,
when they build an SDK client.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pydantic import SecretStr

from docintel.config import Settings, get_api_key, server_api_key

HOSTED_PROVIDERS = ("openai", "anthropic", "gemini")
PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini"}
# Where each provider's users create keys (checked 2026-11-14).
KEY_PAGES = {
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://platform.claude.com/settings/keys",
    "gemini": "https://aistudio.google.com/apikey",
}

MIN_KEY_LENGTH = 20
MAX_KEY_LENGTH = 512
_KEY_CHARACTERS = re.compile(r"[A-Za-z0-9_\-.:+/=]+")
# Prefixes that identify another provider's key. Such a key is refused instead of being sent to
# the wrong company. Google documents no prefix for its newer "auth" keys, so for Gemini only
# OpenAI and Anthropic prefixes are refused.
_FOREIGN_PREFIXES: dict[str, tuple[tuple[str, str], ...]] = {
    "openai": (("sk-ant-", "an Anthropic"), ("AIza", "a Google")),
    "anthropic": (
        ("sk-proj-", "an OpenAI"),
        ("sk-svcacct-", "an OpenAI"),
        ("sk-admin-", "an OpenAI"),
        ("AIza", "a Google"),
    ),
    "gemini": (("sk-ant-", "an Anthropic"), ("sk-", "an OpenAI")),
}

# Environment variables that the installed provider SDKs apply to every request by themselves,
# even when DocIntel passes the key and endpoint explicitly (checked against openai 3.51,
# anthropic 2.8 and google-genai 3.3). With a key typed in by a user, they would add the server
# operator's extra headers to that user's requests, or copy request content into the operator's
# logs or telemetry. Keys entered in the browser are therefore refused while any of them is set.
# The SDKs' other environment settings (endpoints, organization and project IDs, server
# credentials, the Vertex AI switch) are overridden when the client is built.
UNSAFE_SDK_ENV_VARS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_CUSTOM_HEADERS", "OPENAI_LOG"),
    "anthropic": (
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_LOG",
        "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE",
    ),
    "gemini": (),
}

KeySource = Literal["session", "server"]


class KeyFormatError(ValueError):
    """The text entered can't be used as a key. The message never contains the text."""


@dataclass(frozen=True)
class Credential:
    """An API key and where it came from. ``repr`` and ``str`` never show the key."""

    provider: str
    secret: SecretStr = field(repr=False)
    source: KeySource

    @property
    def is_session_key(self) -> bool:
        """Keys typed in a browser session get SDK clients sealed off from server settings."""
        return self.source == "session"


def check_key_format(provider: str, raw: str | None) -> str:
    """Return the cleaned key, or raise :class:`KeyFormatError` with a message for the user.

    Nothing is sent anywhere: this only catches empty or mangled input and keys that belong to
    a different provider.
    """
    if provider not in HOSTED_PROVIDERS:
        raise KeyFormatError("Offline demo mode does not use an API key.")
    name = PROVIDER_NAMES[provider]
    key = (raw or "").strip()
    if not key:
        raise KeyFormatError(f"Paste your {name} API key first.")
    if len(key) < MIN_KEY_LENGTH:
        raise KeyFormatError("That is too short to be an API key. Copy the whole key again.")
    if len(key) > MAX_KEY_LENGTH:
        raise KeyFormatError("That is too long to be an API key. Paste only the key.")
    if not _KEY_CHARACTERS.fullmatch(key):
        raise KeyFormatError(
            "API keys don't contain spaces or unusual characters. Copy the key again, exactly as "
            "the provider shows it."
        )
    for prefix, owner in _FOREIGN_PREFIXES[provider]:
        if key.startswith(prefix):
            raise KeyFormatError(
                f"That looks like {owner} key, so it was not used or sent anywhere. Choose the "
                f"matching provider, or paste your {name} key."
            )
    return key


class SessionKeyStore:
    """The API keys typed in by one browser session, at most one per provider.

    One instance lives in that session's ``st.session_state`` and nowhere else. It is never
    written to disk, ``os.environ``, logs, URLs or Streamlit's cross-session caches, and its
    ``repr`` lists provider names only.
    """

    def __init__(self) -> None:
        self._keys: dict[str, SecretStr] = {}

    def set(self, provider: str, raw: str | None) -> None:
        self._keys[provider] = SecretStr(check_key_format(provider, raw))

    def get(self, provider: str) -> SecretStr | None:
        return self._keys.get(provider)

    def remove(self, provider: str) -> bool:
        return self._keys.pop(provider, None) is not None

    def clear(self) -> None:
        self._keys.clear()

    def providers(self) -> list[str]:
        return sorted(self._keys)

    def __contains__(self, provider: object) -> bool:
        return provider in self._keys

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"SessionKeyStore(providers={self.providers()})"

    __str__ = __repr__


def resolve_credential(
    provider: str,
    settings: Settings,
    session_keys: SessionKeyStore | None,
    *,
    server_env: Mapping[str, str] | None = None,
) -> Credential | None:
    """The key a browser session should use for ``provider``, or None.

    Precedence: the key this session entered; then, only in owner mode, the server's key. In BYOK
    mode the server's key is never returned, so a user can't spend the operator's credit.
    ``server_env`` replaces the real server environment in tests.
    """
    if provider not in HOSTED_PROVIDERS:
        return None
    own = session_keys.get(provider) if session_keys is not None else None
    if own is not None:
        return Credential(provider, own, "session")
    if settings.key_mode == "owner":
        server = (
            server_api_key(provider) if server_env is None else get_api_key(provider, server_env)
        )
        if server is not None:
            return Credential(provider, server, "server")
    return None


def server_credential(provider: str) -> Credential | None:
    """The server's own key, for the command-line evaluation runner (the key owner's use)."""
    key = server_api_key(provider)
    return Credential(provider, key, "server") if key is not None else None


def unsafe_sdk_environment(provider: str, env: Mapping[str, str] | None = None) -> list[str]:
    """Names of set variables that would leak server settings into requests made with a user key."""
    source = os.environ if env is None else env
    found = []
    for name in UNSAFE_SDK_ENV_VARS.get(provider, ()):
        value = (source.get(name) or "").strip()
        if not value:
            continue
        if name.endswith("_TRACES_CONTENT_MODE") and value.lower() != "content":
            continue  # only "content" makes the SDK copy prompts and outputs into traces
        found.append(name)
    return found
