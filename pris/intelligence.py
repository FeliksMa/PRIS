from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from .config import Settings
from .db import Database
from .http import post_json
from .models import Assessment, Paper


def keyword_score(paper: Paper, config: dict[str, Any]) -> float:
    profile = config.get("profile", {})
    weights = profile.get("weights", {})
    interests = profile.get("interests", {}).get(paper.field, [])
    excluded = profile.get("exclude", {}).get("keywords", [])
    text = f"{paper.title} {paper.abstract}".lower()
    matches = min(sum(1 for keyword in interests if keyword.lower() in text), 5)
    penalties = sum(1 for keyword in excluded if keyword.lower() in text)
    quality_by_type = {
        "peer_reviewed": 2.5,
        "working_paper": 2.0,
        "institution_research": 2.0,
        "institution_analysis": 1.8,
        "industry_primary": 1.5,
        "institution_data": 1.2,
        "institution_update": 1.0,
        "preprint": 1.0,
    }
    quality = quality_by_type.get(paper.source_type, 1.0)
    verified = 1.5 if paper.verified else -2.0
    novelty = 0.0
    if paper.field == "ai":
        novelty_terms = ("new", "novel", "architecture", "mechanism", "paradigm", "framework", "method")
        novelty = 1.5 if any(term in paper.title.lower() for term in novelty_terms) else 0.0
    return round(weights.get(paper.field, 0.1) * 10 + matches * 1.8 + novelty + quality + verified - penalties * 3, 2)


def prefilter(papers: list[Paper], config: dict[str, Any]) -> list[Paper]:
    maximum = int(config["system"].get("max_candidates", 50))
    hard_exclude = config.get("profile", {}).get("hard_exclude", {})
    eligible = []
    for paper in papers:
        if config.get("profile", {}).get("weights", {}).get(paper.field, 0) <= 0:
            continue
        text = f"{paper.title} {paper.abstract}".lower()
        blocked = hard_exclude.get(paper.field, [])
        if any(term.lower() in text for term in blocked):
            continue
        eligible.append(paper)
    return sorted(eligible, key=lambda p: keyword_score(p, config), reverse=True)[:maximum]


def heuristic_assessments(papers: list[Paper], config: dict[str, Any]) -> list[Assessment]:
    results: list[Assessment] = []
    for paper in papers:
        score = keyword_score(paper, config)
        sentence = paper.abstract[:700].rstrip() if paper.abstract else "来源尚未提供摘要，请通过原始页面查看。"
        results.append(Assessment(
            paper_id=paper.id,
            score=score,
            one_sentence=sentence,
            why_important=f"与个人研究兴趣匹配；来源为 {paper.source}。",
            research_question="当前未调用模型，研究问题需根据完整摘要或原文进一步整理。",
            background="当前仅保留来源提供的摘要，尚未进行中文背景解释。",
            article_structure="尚未读取全文；不能仅凭标题编造文章章节和论证结构。",
            method="待阅读原文确认",
            technical_core="摘要不足以确认是否存在必须解释的数学或技术核心。",
            main_findings=sentence,
            contribution="待根据摘要和原文进一步判断。",
            evidence="当前仅依据元数据和摘要",
            limitations="尚未读取全文",
            connection=f"归入 {paper.field} 主题",
            reading_advice="先阅读摘要，感兴趣后请求深读",
        ))
    return results


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("模型没有返回 JSON 数组")
    return json.loads(text[start:end + 1])


def remove_unsupported_speculation(item: Assessment) -> Assessment:
    """Replace model speculation with an explicit evidence boundary."""
    speculative = ("可能使用", "可能采用", "可能通过", "预期发现", "预计发现", "或许", "推测")
    if any(marker in item.method for marker in speculative):
        item.method = "摘要未明确说明具体方法，不能据此推断。"
    if any(marker in item.main_findings for marker in speculative):
        item.main_findings = "摘要未提供可确认的具体结果，不能据此推断。"
    if any(marker in item.technical_core for marker in speculative):
        item.technical_core = "摘要未提供可确认的数学、技术机制或识别细节，不能据此推断。"
    return item


def assess(papers: list[Paper], settings: Settings, db: Database) -> list[Assessment]:
    config = settings.raw
    api_key = settings.secret("DEEPSEEK_API_KEY")
    if not api_key:
        return heuristic_assessments(papers, config)
    ds = config["deepseek"]
    today = date.today().isoformat()
    if db.daily_cost(today) >= float(ds.get("daily_budget_usd", 0.30)):
        return heuristic_assessments(papers, config)

    payload_papers = [{
        "id": p.id, "title": p.title, "authors": p.authors[:8], "abstract": p.abstract[:3500],
        "published": p.published, "source": p.source, "source_type": p.source_type,
        "field": p.field, "doi": p.doi, "verified": p.verified,
        "full_text_excerpt": p.raw.get("full_text_excerpt", ""),
        "evidence_scope": p.raw.get("evidence_scope", "仅元数据和摘要"),
    } for p in papers]
    system_prompt = """你是严谨的个人研究助理。只能依据提供的元数据、摘要及明确给出的全文选段判断，不得编造未提供的内容。
下列领域说明和长度要求是默认值；用户当前的 user_profile 和 style_guidance 优先。
depth为compact时减少重复、紧凑解释，为deep时展开机制与识别假设，为expanded时完整清晰解释。
用户核心关注行为经济学、不确定性、现实宏观和实证经济学；AI方面关注设计层面的机制创新：
包括新模型架构、MoE与路由、Attention、训练与推理方法、Skills优化、表示与记忆、World Model、
编程抽象和Agent系统等，不得把兴趣窄化为Agent方向。社会人文仅需清晰、现实、有解释力。
经济学优先可靠证据，AI可保留少量有解释力的早期信号。
请把内容讲明白。数学可以使用，但必须服务于理解：若核心贡献依赖效用函数、识别方程、估计量、均衡条件
或关键模型机制，可给出必要的 Markdown LaTeX 公式并逐项解释直觉；不要堆砌无助于理解结论的推导。
代码通常不必展开，除非代码或实现机制本身就是文章贡献。重点条目应让读者不看原文也能理解
研究在问什么、为什么会问、作者怎样展开论证、得到什么结论以及结论有什么边界。
对 source_type 为 institution_data、institution_analysis 或 institution_update 的现实经济动态，
不要硬套学术论文口吻：research_question 写“本次核心变化是什么”，background 交代比较基准和宏观背景，
article_structure 写信息链条，method 只说明数据口径或证据来源，main_findings 展开关键数据与可能由来源明确支持的原因，
contribution 写它更新了什么现实判断，reading_advice 写后续应观察的指标。来源未解释原因时不要自行归因。
对 AI 内容重点解释核心原理、相对旧方法的新意、实际用途、成熟度和限制，不展开无意义代码细节。

请返回严格 JSON 对象，顶层只有 assessments 数组。每项必须包含：
- id, score(0-100)
- one_sentence：120-240字的内容概览，可用2-4句，不要只改写标题
- research_question：作者真正要回答的问题
- background：问题背景和已有认识的缺口
- article_structure：根据摘要能够确认的论证路径或文章架构；说明先做什么、再做什么、如何得出结论
- method：数据、样本、实验、模型、识别策略或比较方法
- technical_core：理解文章所必需的数学、技术机制或识别假设；有必要时给出1-2条公式并解释变量和直觉，
  没有必要或摘要没有提供时明确说明，不得自行补造
- main_findings：尽量用150-300字分层说明主要发现，包含摘要明确给出的方向、机制、异质性或数量级；摘要没给的数据绝不补造
- contribution：相对已有认识新增了什么
- why_important：为什么值得该用户知道
- evidence：明确是仅摘要、元数据还是全文
- limitations：证据边界、外推限制和摘要无法判断之处
- connection：与用户知识体系的联系
- reading_advice：是否值得深读以及深读时应重点检查什么

若摘要不足，必须明确写“摘要未提供”“摘要未说明”或“尚未读取全文”。article_structure只能写
“根据摘要可确认的结构”，绝不能虚构章节、回归、实验或结果。"""
    response = post_json(
        ds.get("base_url", "https://api.deepseek.com").rstrip("/") + "/chat/completions",
        {
            "model": ds.get("model", "deepseek-v4-flash"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({
                    "style_guidance": config.get("profile", {}).get("style", {}),
                    "user_profile": config.get("profile", {}),
                    "items": payload_papers,
                }, ensure_ascii=False)},
            ],
            "thinking": {"type": "enabled" if ds.get("thinking", False) else "disabled"},
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    usage = response.get("usage", {})
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    cost = input_tokens / 1_000_000 * float(ds.get("input_usd_per_million", 0.22))
    cost += output_tokens / 1_000_000 * float(ds.get("output_usd_per_million", 0.66))
    db.record_usage(today, ds.get("model", "deepseek-v4-flash"), input_tokens, output_tokens, cost)
    content = response["choices"][0]["message"]["content"]
    decoded = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I | re.S))
    rows = decoded.get("assessments", []) if isinstance(decoded, dict) else decoded
    results = [remove_unsupported_speculation(Assessment(
        paper_id=row["id"], score=float(row.get("score", 0)),
        one_sentence=row.get("one_sentence", ""), why_important=row.get("why_important", ""),
        research_question=row.get("research_question", ""), background=row.get("background", ""),
        article_structure=row.get("article_structure", ""), method=row.get("method", ""),
        technical_core=row.get("technical_core", ""),
        main_findings=row.get("main_findings", ""), contribution=row.get("contribution", ""),
        evidence=row.get("evidence", ""),
        limitations=row.get("limitations", ""), connection=row.get("connection", ""),
        reading_advice=row.get("reading_advice", ""),
    )) for row in rows if row.get("id")]
    return results


def assign_tiers(assessments: list[Assessment], config: dict[str, Any]) -> list[Assessment]:
    ordered = sorted(assessments, key=lambda item: item.score, reverse=True)
    paper_fields = config.get("_paper_fields", {})
    paper_regions = config.get("_paper_regions", {})
    paper_source_types = config.get("_paper_source_types", {})
    paper_texts = config.get("_paper_texts", {})
    mix = config.get("profile", {}).get("daily_mix", {})
    china_share = float(config.get("profile", {}).get("economics_china_share", 0.5))

    def choose(pool: list[Assessment], quotas: dict[str, Any], maximum: int) -> list[Assessment]:
        chosen: list[Assessment] = []
        chosen_ids: set[str] = set()
        for field, raw_count in quotas.items():
            count = int(raw_count)
            field_items = [item for item in pool if paper_fields.get(item.paper_id) == field]
            if field == "economics" and count > 1:
                def region_pick(items: list[Assessment], target: int) -> list[Assessment]:
                    china_count = round(target * china_share)
                    china_items = [item for item in items if paper_regions.get(item.paper_id) == "china"]
                    global_items = [item for item in items if paper_regions.get(item.paper_id) != "china"]
                    picked = china_items[:china_count] + global_items[:target - min(china_count, len(china_items))]
                    if len(picked) < target:
                        used = {item.paper_id for item in picked}
                        picked.extend(item for item in items if item.paper_id not in used)
                    return picked[:target]

                academic_types = {"peer_reviewed", "working_paper", "institution_research"}
                academic = [item for item in field_items if paper_source_types.get(item.paper_id) in academic_types]
                real_world = [item for item in field_items if paper_source_types.get(item.paper_id) not in academic_types]
                topic_groups = {
                    "inflation": ("cpi", "ppi", "consumer price", "producer price", "居民消费价格", "工业生产者"),
                    "growth": ("gdp", "economic growth", "国内生产总值", "经济增长"),
                    "labor": ("employment", "unemployment", "labor market", "就业", "失业"),
                    "monetary": ("monetary policy", "interest rate", "fomc", "货币政策", "利率"),
                    "trade": ("trade", "export", "import", "贸易", "出口", "进口"),
                    "housing": ("housing", "real estate", "房价", "房地产"),
                    "activity": ("pmi", "industrial production", "采购经理", "工业生产"),
                }
                seen_topics: set[str] = set()
                unique_real_world: list[Assessment] = []
                for item in real_world:
                    text = paper_texts.get(item.paper_id, "")
                    topic = next((name for name, terms in topic_groups.items() if any(term in text for term in terms)), "")
                    if topic and topic in seen_topics:
                        continue
                    if topic:
                        seen_topics.add(topic)
                    unique_real_world.append(item)
                real_world = unique_real_world
                academic_share = float(config.get("profile", {}).get("economics_academic_share", 0.5))
                academic_count = round(count * academic_share)
                candidates = region_pick(academic, academic_count) + region_pick(real_world, count - academic_count)
                if len(candidates) < count:
                    used = {item.paper_id for item in candidates}
                    eligible_economics = academic + real_world
                    candidates.extend(item for item in eligible_economics if item.paper_id not in used)
            else:
                candidates = field_items
            for item in candidates[:count]:
                if item.paper_id not in chosen_ids:
                    chosen.append(item)
                    chosen_ids.add(item.paper_id)
        for item in pool:
            if len(chosen) >= maximum:
                break
            if item.paper_id not in chosen_ids:
                chosen.append(item)
                chosen_ids.add(item.paper_id)
        field_weights = config.get("profile", {}).get("weights", {})
        return sorted(
            chosen[:maximum],
            key=lambda item: (field_weights.get(paper_fields.get(item.paper_id, ""), 0), item.score),
            reverse=True,
        )

    focus_max = int(config["system"].get("daily_focus", 5))
    quick_max = int(config["system"].get("daily_quick", 8))
    focus = choose(ordered, mix.get("focus", {"economics": 3, "ai": 2}), focus_max)
    focus_ids = {item.paper_id for item in focus}
    remaining = [item for item in ordered if item.paper_id not in focus_ids]
    quick = choose(remaining, mix.get("quick", {"economics": 5, "ai": 2, "humanities": 1}), quick_max)
    for item in focus:
        item.tier = "focus"
    for item in quick:
        item.tier = "quick"
    return focus + quick
