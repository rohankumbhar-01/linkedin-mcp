"""Approval-first LinkedIn MCP tools.

This server only uses LinkedIn's official API. Available operations depend on
permissions granted to the LinkedIn developer application.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

APP_NAME = "LinkedIn MCP"
API_BASE = "https://api.linkedin.com"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
TOKEN_PATH = Path(os.getenv("LINKEDIN_TOKEN_PATH", "~/.linkedin-mcp/token.json")).expanduser()

mcp = FastMCP(APP_NAME, json_response=True)
_pending_state: str | None = None


def _client_config() -> tuple[str, str, str]:
    client_id = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8765/callback").strip()
    if not client_id or not client_secret:
        raise ValueError("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in your environment or .env file.")
    return client_id, client_secret, redirect_uri


def _load_token() -> dict[str, Any] | None:
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_token(token: dict[str, Any]) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(token, indent=2), encoding="utf-8")
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass


def _access_token() -> str:
    token = _load_token()
    if not token or not token.get("access_token"):
        raise ValueError("LinkedIn is not connected. Call linkedin_start_oauth, authorize the URL, then call linkedin_exchange_code.")
    expires_at = token.get("expires_at")
    if expires_at and time.time() >= float(expires_at):
        raise ValueError("Stored LinkedIn token has expired. Reconnect using linkedin_start_oauth and linkedin_exchange_code.")
    return str(token["access_token"])


def _headers() -> dict[str, str]:
    version = os.getenv("LINKEDIN_API_VERSION", "202601").strip()
    return {
        "Authorization": f"Bearer {_access_token()}",
        "LinkedIn-Version": version,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def _api_error(response: httpx.Response) -> dict[str, Any]:
    try:
        detail = response.json()
    except ValueError:
        detail = response.text[:1000]
    return {"ok": False, "status_code": response.status_code, "error": detail}


@mcp.tool()
def linkedin_connection_status() -> dict[str, Any]:
    """Check whether a LinkedIn access token is stored; never returns the token."""
    token = _load_token()
    if not token:
        return {"connected": False, "message": "No token stored. Start OAuth to connect LinkedIn."}
    expired = bool(token.get("expires_at") and time.time() >= float(token["expires_at"]))
    return {"connected": not expired, "expired": expired, "scopes": token.get("scope", "unknown"), "token_path": str(TOKEN_PATH)}


@mcp.tool()
def linkedin_start_oauth() -> dict[str, Any]:
    """Create a LinkedIn OAuth authorization URL. Open it and sign in to authorize the app."""
    global _pending_state
    client_id, _, redirect_uri = _client_config()
    _pending_state = secrets.token_urlsafe(24)
    scopes = os.getenv("LINKEDIN_SCOPES", "openid profile email w_member_social").strip()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": _pending_state,
        "scope": scopes,
    }
    return {
        "authorization_url": AUTH_URL + "?" + urlencode(params),
        "redirect_uri": redirect_uri,
        "requested_scopes": scopes.split(),
        "next_step": "Open the URL, approve the requested permissions, then pass the returned code and state to linkedin_exchange_code. The requested scopes must be enabled for your LinkedIn developer app.",
    }


@mcp.tool()
def linkedin_exchange_code(code: str, state: str) -> dict[str, Any]:
    """Exchange an OAuth authorization code for a token after checking the state generated in this session."""
    global _pending_state
    if not _pending_state or not secrets.compare_digest(state, _pending_state):
        raise ValueError("OAuth state did not match. Start OAuth again and use the state from the new authorization URL.")
    client_id, client_secret, redirect_uri = _client_config()
    with httpx.Client(timeout=20) as client:
        response = client.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.is_error:
        return _api_error(response)
    data = response.json()
    data["expires_at"] = time.time() + int(data.get("expires_in", 0))
    _save_token(data)
    _pending_state = None
    return {"connected": True, "expires_in": data.get("expires_in"), "scopes": data.get("scope", "unknown"), "message": "Token saved with owner-only file permissions. Never share token.json."}


@mcp.tool()
def linkedin_get_my_profile() -> dict[str, Any]:
    """Read the signed-in member's basic OpenID profile fields, if the app has the required permissions."""
    with httpx.Client(timeout=20) as client:
        response = client.get(USERINFO_URL, headers=_headers())
    if response.is_error:
        return _api_error(response)
    return {"ok": True, "profile": response.json(), "note": "This is the profile data LinkedIn exposes to this app; it is not the full editable LinkedIn profile."}


@mcp.tool()
def linkedin_draft_profile_changes(current_profile: str, target_role: str, skills: str, achievements: str = "") -> dict[str, Any]:
    """Prepare suggested headline/About/experience text. This tool drafts only; it does not edit LinkedIn."""
    return {
        "approval_required": True,
        "current_profile_received": current_profile,
        "target_role": target_role,
        "skills": [x.strip() for x in skills.split(",") if x.strip()],
        "achievements": achievements,
        "instructions_for_llm": (
            "Use the supplied context to propose a truthful LinkedIn headline (under 220 characters), About section, "
            "and achievement-focused experience bullets. Do not invent metrics, employers, credentials, or outcomes. "
            "Return a before/after table and a list of facts that need user confirmation. No LinkedIn write API is called."
        ),
    }


@mcp.tool()
def linkedin_prepare_post(text: str, visibility: str = "PUBLIC") -> dict[str, Any]:
    """Validate and prepare a post for review; does not publish it."""
    if visibility not in {"PUBLIC", "CONNECTIONS"}:
        raise ValueError("visibility must be PUBLIC or CONNECTIONS")
    clean = text.strip()
    if not clean:
        raise ValueError("Post text cannot be empty.")
    return {"status": "draft", "text": clean, "visibility": visibility, "approval_required": True, "next_step": "Review this draft. Publishing is a separate tool and must be explicitly requested."}


@mcp.tool()
def linkedin_publish_approved_post(text: str, approved: bool, visibility: str = "PUBLIC") -> dict[str, Any]:
    """Publish a post through LinkedIn's official Posts API only when the caller explicitly confirms approval."""
    if not approved:
        return {"published": False, "message": "Not published. Set approved=true only after the user has explicitly approved this exact text."}
    if visibility not in {"PUBLIC", "CONNECTIONS"}:
        raise ValueError("visibility must be PUBLIC or CONNECTIONS")
    clean = text.strip()
    if not clean:
        raise ValueError("Post text cannot be empty.")
    with httpx.Client(timeout=20) as client:
        me_response = client.get(USERINFO_URL, headers=_headers())
        if me_response.is_error:
            return {"published": False, "stage": "identity_lookup", **_api_error(me_response)}
        me = me_response.json()
        subject = me.get("sub")
        if not subject:
            return {"published": False, "error": "LinkedIn userinfo did not return sub; cannot determine member identity."}
        member_urn = subject if str(subject).startswith("urn:li:") else f"urn:li:person:{subject}"
        payload = {
            "author": member_urn,
            "commentary": clean,
            "visibility": "PUBLIC" if visibility == "PUBLIC" else "CONNECTIONS",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        response = client.post(f"{API_BASE}/rest/posts", headers=_headers(), json=payload)
    if response.is_error:
        return {"published": False, "stage": "publish", **_api_error(response), "note": "Check LinkedIn product access, API version, and w_member_social permission."}
    return {"published": True, "post_id": response.headers.get("x-restli-id"), "status_code": response.status_code}


@mcp.tool()
def linkedin_capabilities_and_limits() -> dict[str, Any]:
    """Explain which features are implemented and which depend on LinkedIn API approval."""
    return {
        "implemented": ["OAuth authorization-code exchange", "basic OpenID profile read", "profile rewrite planning", "post draft preparation", "approval-gated post publishing via official Posts API"],
        "not_implemented_or_not_generally_available": ["automatic editing of headline/About/experience/skills: LinkedIn does not generally expose these profile-write operations to ordinary apps", "reading arbitrary feed posts and connections", "full personal analytics unless the app is approved for the relevant products"],
        "requirements": ["LinkedIn developer app", "approved products/scopes", "valid redirect URI", "client ID and secret stored securely", "a currently supported LinkedIn API version"],
        "safety": "Never paste access tokens or client secrets into an LLM prompt. Keep publishing approval explicit.",
    }


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
