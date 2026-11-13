"""Persistent model connection settings shared by the API and worker processes."""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

import certifi

from .db import connect
from . import provider_http

UNSET = object()

def _official(base_url):
    return urlsplit(base_url).hostname == "api.openai.com"

def _default_effort(base_url):
    return "low" if _official(base_url) else None

def _resolve_profiles(config):
    official = _official(config["base_url"])
    config["hierarchy_model"] = config.get("_hierarchy_model_override") or ("gpt-6-luna" if official else config["model"])
    config["hierarchy_reasoning_effort"] = config.get("_hierarchy_effort_override") if config.get("_hierarchy_effort_set") else ("high" if official else config.get("reasoning_effort"))
    config["hierarchy_model_configured"] = bool(config.get("_hierarchy_model_override"))
    config["hierarchy_reasoning_effort_configured"] = bool(config.get("_hierarchy_effort_set"))
    return config

def profile_config(config, purpose="harness"):
    if purpose not in {"harness", "hierarchy"}:
        raise ValueError("Unknown model workflow")
    result = dict(config)
    if purpose == "hierarchy":
        result["model"] = config.get("hierarchy_model") or ("gpt-6-luna" if _official(config["base_url"]) else config["model"])
        result["reasoning_effort"] = config.get("hierarchy_reasoning_effort") if "hierarchy_reasoning_effort" in config else ("high" if _official(config["base_url"]) else config.get("reasoning_effort"))
    return result


def validate_connection(base_url: str, model: str, api_mode: str) -> dict:
    base_url = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTP or HTTPS base URL") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or any(char.isspace() for char in base_url)):
        raise ValueError("Base URL must use HTTP or HTTPS without credentials, query parameters or fragments")
    model = model.strip()
    if not model or len(model) > 500 or any(ord(char) < 32 for char in model):
        raise ValueError("Enter a model identifier between 1 and 500 characters")
    if api_mode not in {"responses", "chat_completions"}:
        raise ValueError("API mode must be responses or chat_completions")
    return {"base_url": urlunsplit(parsed), "model": model, "api_mode": api_mode}


def load_agent_config() -> dict:
    """Return a fresh connection snapshot. Saved fields take precedence over env."""
    config = {
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": os.environ.get("GRAPHIFIER_AGENT_MODEL", "gpt-6-luna"),
        "api_mode": os.environ.get("GRAPHIFIER_AGENT_API", "responses"),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "reasoning_effort": os.environ.get("GRAPHIFIER_AGENT_REASONING_EFFORT") or _default_effort(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")),
        "_hierarchy_model_override": os.environ.get("GRAPHIFIER_HIERARCHY_MODEL") or None,
        "_hierarchy_effort_override": os.environ.get("GRAPHIFIER_HIERARCHY_REASONING_EFFORT") or None,
        "_hierarchy_effort_set": "GRAPHIFIER_HIERARCHY_REASONING_EFFORT" in os.environ,
        "saved": False,
        "base_url_configured": bool(os.environ.get("OPENAI_BASE_URL")),
    }
    with connect() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_configuration'").fetchone()
        row = c.execute("SELECT * FROM agent_configuration WHERE id=1").fetchone() if exists else None
    if row:
        environment_endpoint = config["base_url"]
        config.update(base_url=row["base_url"], model=row["model"], api_mode=row["api_mode"], saved=True, base_url_configured=True)
        config["reasoning_effort"] = row["reasoning_effort"] if "reasoning_effort" in row.keys() else None
        if "hierarchy_model" in row.keys() and row["hierarchy_model"]:
            config["_hierarchy_model_override"] = row["hierarchy_model"]
        if "hierarchy_effort_set" in row.keys() and row["hierarchy_effort_set"]:
            config["_hierarchy_effort_override"] = row["hierarchy_reasoning_effort"]
            config["_hierarchy_effort_set"] = True
        # NULL inherits the environment. Empty string explicitly disables its key.
        if row["api_key"] is not None:
            config["api_key"] = row["api_key"]
        elif not provider_http.same_endpoint(environment_endpoint, row["base_url"]):
            config["api_key"] = ""
    return _resolve_profiles(config)


def public_agent_config(config: dict | None = None) -> dict:
    config = config or load_agent_config()
    key_configured = bool(config["api_key"])
    return {
        "enabled": bool(key_configured or config["base_url_configured"]),
        "base_url": config["base_url"],
        "model": config["model"],
        "reasoning_effort": config.get("reasoning_effort"),
        "hierarchy_model": config["hierarchy_model"],
        "hierarchy_reasoning_effort": config.get("hierarchy_reasoning_effort"),
        "hierarchy_model_configured": config.get("hierarchy_model_configured", False),
        "hierarchy_reasoning_effort_configured": config.get("hierarchy_reasoning_effort_configured", False),
        "api": config["api_mode"],
        "api_mode": config["api_mode"],
        "api_key_configured": key_configured,
        "key_configured": key_configured,
        "base_url_configured": config["base_url_configured"],
        "saved": config["saved"],
    }


def _validate_hierarchy_model(value):
    if value is UNSET or value is None: return
    if not isinstance(value,str) or not value.strip() or len(value)>500 or any(ord(c)<32 for c in value):
        raise ValueError("Enter a hierarchy model identifier between 1 and 500 characters")


def candidate_agent_config(base_url: str, model: str, api_mode: str,
                           api_key: str | None = None, clear_api_key: bool = False,
                           reasoning_effort=UNSET, hierarchy_model=UNSET, hierarchy_reasoning_effort=UNSET) -> dict:
    if reasoning_effort is not UNSET: validate_reasoning_effort(reasoning_effort)
    if hierarchy_reasoning_effort is not UNSET: validate_reasoning_effort(hierarchy_reasoning_effort)
    _validate_hierarchy_model(hierarchy_model)
    config = load_agent_config()
    if reasoning_effort is not UNSET:
        config["reasoning_effort"] = reasoning_effort
    elif not config["saved"] and "GRAPHIFIER_AGENT_REASONING_EFFORT" not in os.environ:
        config["reasoning_effort"] = _default_effort(base_url)
    values = validate_connection(base_url, model, api_mode)
    if not provider_http.same_endpoint(config["base_url"], values["base_url"]):
        config["api_key"] = ""
    config.update(values)
    if hierarchy_model is not UNSET:
        config["_hierarchy_model_override"] = hierarchy_model.strip() if hierarchy_model else os.environ.get("GRAPHIFIER_HIERARCHY_MODEL") or None
    if hierarchy_reasoning_effort is not UNSET:
        config["_hierarchy_effort_override"] = hierarchy_reasoning_effort
        config["_hierarchy_effort_set"] = True
    if clear_api_key:
        config["api_key"] = ""
    elif api_key and api_key.strip():
        config["api_key"] = api_key.strip()
    if len(config["api_key"]) > 8192 or any(ord(char) < 32 for char in config["api_key"]):
        raise ValueError("API key contains invalid characters or is too long")
    config["base_url_configured"] = True
    return _resolve_profiles(config)


def save_agent_config(base_url: str, model: str, api_mode: str,
                      api_key: str | None = None, clear_api_key: bool = False,
                      reasoning_effort=UNSET, hierarchy_model=UNSET, hierarchy_reasoning_effort=UNSET) -> dict:
    if reasoning_effort is not UNSET: validate_reasoning_effort(reasoning_effort)
    if hierarchy_reasoning_effort is not UNSET: validate_reasoning_effort(hierarchy_reasoning_effort)
    _validate_hierarchy_model(hierarchy_model)
    values = validate_connection(base_url, model, api_mode)
    if api_key and (len(api_key) > 8192 or any(ord(char) < 32 for char in api_key)):
        raise ValueError("API key contains invalid characters or is too long")
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM agent_configuration WHERE id=1").fetchone()
        saved_key = row["api_key"] if row else None
        previous_endpoint = row["base_url"] if row else os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not provider_http.same_endpoint(previous_endpoint, values["base_url"]):
            # Persist an explicit clear: NULL would revive an environment key.
            saved_key = ""
        if clear_api_key:
            saved_key = ""
        elif api_key and api_key.strip():
            saved_key = api_key.strip()
        effort = reasoning_effort if reasoning_effort is not UNSET else row["reasoning_effort"] if row else os.environ.get("GRAPHIFIER_AGENT_REASONING_EFFORT") or _default_effort(values["base_url"])
        hmodel = (hierarchy_model.strip() if hierarchy_model else None) if hierarchy_model is not UNSET else row["hierarchy_model"] if row else None
        heffort = hierarchy_reasoning_effort if hierarchy_reasoning_effort is not UNSET else row["hierarchy_reasoning_effort"] if row else None
        hset = 1 if hierarchy_reasoning_effort is not UNSET else row["hierarchy_effort_set"] if row else 0
        c.execute("""INSERT INTO agent_configuration(id,base_url,model,api_mode,api_key,reasoning_effort,hierarchy_model,hierarchy_reasoning_effort,hierarchy_effort_set)
                     VALUES(1,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                     base_url=excluded.base_url,model=excluded.model,
                     api_mode=excluded.api_mode,api_key=excluded.api_key,reasoning_effort=excluded.reasoning_effort,
                     hierarchy_model=excluded.hierarchy_model,hierarchy_reasoning_effort=excluded.hierarchy_reasoning_effort,
                     hierarchy_effort_set=excluded.hierarchy_effort_set""",
                  (values["base_url"], values["model"], values["api_mode"], saved_key, effort,hmodel,heffort,hset))
    return public_agent_config()


def test_agent_connection(config: dict) -> dict:
    headers = {"Accept": "application/json"}
    if config["api_key"]:
        headers["Authorization"] = f"Bearer {config['api_key']}"
    request = urllib.request.Request(f"{config['base_url']}/models", headers=headers)
    cafile = os.environ.get("SSL_CERT_FILE") or certifi.where()
    try:
        with provider_http.urlopen(request, timeout=10, context=ssl.create_default_context(cafile=cafile)) as response:
            payload = json.loads(response.read(2_000_001))
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise ValueError("Invalid model listing")
        models = sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)})
        return {"status": "ok", "models": models, "selected_model_available": config["model"] in models, "hierarchy_model_available": profile_config(config,"hierarchy")["model"] in models}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Model listing request returned HTTP {exc.code}") from exc
    except (TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError("Could not read the endpoint's model list. Check its address and availability.") from exc


def validate_reasoning_effort(value):
    if value not in {None, "none", "minimal", "low", "medium", "high", "xhigh"}:
        raise ValueError("Invalid reasoning effort")
