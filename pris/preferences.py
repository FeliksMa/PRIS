from __future__ import annotations

import copy
import json
import math
import os
import threading
from pathlib import Path
from typing import Any

FIELDS = ("economics", "ai", "humanities")
PREFERENCE_LOCK = threading.RLock()


def public_preferences(config: dict[str, Any]) -> dict[str, Any]:
    profile = config.get("profile", {})
    return {
        "daily_focus": config["system"].get("daily_focus", 10),
        "daily_quick": config["system"].get("daily_quick", 5),
        "weights": {field: profile.get("weights", {}).get(field, 0) for field in FIELDS},
        "interests": {field: profile.get("interests", {}).get(field, []) for field in FIELDS},
        "exclude": profile.get("exclude", {}).get("keywords", []),
        "ai_exclude": profile.get("hard_exclude", {}).get("ai", []),
        "economics_china_share": profile.get("economics_china_share", 0.5),
        "economics_academic_share": profile.get("economics_academic_share", 0.5),
        "ai_selection_principle": profile.get("ai_selection_principle", ""),
        "style": copy.deepcopy(profile.get("style", {})),
        "sources": {feed["name"]: feed.get("enabled", True) for feed in config.get("sources", {}).get("rss", [])},
    }


def validate_preferences(value: Any, allowed_sources: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("偏好必须是对象")
    result: dict[str, Any] = {}
    for key, maximum in (("daily_focus", 30), ("daily_quick", 20)):
        n = value.get(key)
        if type(n) is not int or not (0 <= n <= maximum) or (key == "daily_focus" and n < 1):
            raise ValueError(f"{key} 超出允许范围")
        result[key] = n
    weights = value.get("weights", {})
    if not isinstance(weights, dict) or set(weights) != set(FIELDS):
        raise ValueError("需要经济学、AI、人文三个领域的权重")
    normalized = {field: float(weights[field]) for field in FIELDS}
    if any(not math.isfinite(n) or n < 0 or n > 100 for n in normalized.values()) or sum(normalized.values()) <= 0:
        raise ValueError("领域权重必须非负且合计大于零")
    total = sum(normalized.values())
    result["weights"] = {field: n / total for field, n in normalized.items()}
    for key in ("economics_china_share", "economics_academic_share"):
        n = float(value.get(key, 0.5))
        if not math.isfinite(n) or not 0 <= n <= 1:
            raise ValueError("经济学比例应在 0 至 1 之间")
        result[key] = n
    def words(items: Any) -> list[str]:
        if not isinstance(items, list) or len(items) > 150 or any(not isinstance(s, str) or len(s) > 200 for s in items):
            raise ValueError("每组主题最多 150 项，每项不超过 200 字")
        return list(dict.fromkeys(s.strip() for s in items if s.strip()))
    interests = value.get("interests", {})
    result["interests"] = {field: words(interests.get(field, [])) for field in FIELDS}
    for key in ("exclude", "ai_exclude"):
        result[key] = words(value.get(key, []))
    principle = value.get("ai_selection_principle", "")
    if not isinstance(principle, str) or len(principle) > 3000:
        raise ValueError("AI 选择原则过长")
    result["ai_selection_principle"] = principle
    style = value.get("style", {})
    if not isinstance(style, dict) or any(not isinstance(v, str) or len(v) > 3000 for v in style.values()):
        raise ValueError("解读风格应为文本，每项不超过 3000 字")
    result["style"] = {k: style.get(k, "") for k in ("depth", "economics_academic", "economics_news", "ai", "humanities", "general")}
    sources = value.get("sources", {})
    if not isinstance(sources, dict) or set(sources) - allowed_sources or any(type(v) is not bool for v in sources.values()):
        raise ValueError("只能启停已配置的数据源")
    result["sources"] = sources
    return result


def quotas(weights: dict[str, float], count: int) -> dict[str, int]:
    exact = {field: weights[field] * count for field in FIELDS}
    result = {field: int(n) for field, n in exact.items()}
    remainder = count - sum(result.values())
    for field in sorted(FIELDS, key=lambda f: exact[f] - result[f], reverse=True)[:remainder]:
        result[field] += 1
    return result


def apply_preferences(config: dict[str, Any], value: dict[str, Any]) -> None:
    profile = config["profile"]
    for key in ("weights", "interests", "economics_china_share", "economics_academic_share", "ai_selection_principle", "style"):
        profile[key] = copy.deepcopy(value[key])
    profile["exclude"] = {"keywords": value["exclude"]}
    profile["hard_exclude"] = {"ai": value["ai_exclude"]}
    for key in ("daily_focus", "daily_quick"):
        config["system"][key] = value[key]
    profile["daily_mix"] = {
        "focus": quotas(value["weights"], value["daily_focus"]),
        "quick": quotas(value["weights"], value["daily_quick"]),
    }
    for feed in config.get("sources", {}).get("rss", []):
        if feed["name"] in value["sources"]:
            feed["enabled"] = value["sources"][feed["name"]]


def load_overrides(root: Path, config: dict[str, Any]) -> None:
    path = root / "data" / "preferences.json"
    if path.exists():
        allowed = {feed["name"] for feed in config.get("sources", {}).get("rss", [])}
        value = validate_preferences(json.loads(path.read_text(encoding="utf-8")), allowed)
        apply_preferences(config, value)


def save_overrides(root: Path, value: dict[str, Any]) -> None:
    with PREFERENCE_LOCK:
        folder = root / "data"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "preferences.json"
        temp = folder / "preferences.json.tmp"
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
