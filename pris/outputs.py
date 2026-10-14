from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .models import Assessment, Paper


def safe_name(value: str, maximum: int = 90) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .")
    return (value[:maximum] or "untitled").rstrip(" .")


def _identifier(paper: Paper) -> str:
    if paper.doi:
        return f"DOI：[{paper.doi}](https://doi.org/{paper.doi})"
    if paper.external_id:
        return f"主标识：{paper.external_id}"
    return "主标识：缺失"


def _authors(paper: Paper) -> str:
    if not paper.authors:
        return "来源未提供"
    shown = paper.authors[:8]
    suffix = f" 等（共 {len(paper.authors)} 人）" if len(paper.authors) > 8 else ""
    return ", ".join(shown) + suffix


def write_daily_report(
    vault: Path,
    papers: dict[str, Paper],
    assessments: list[Assessment],
    errors: list[str],
    runner_id: str,
) -> Path:
    today = date.today().isoformat()
    folder = vault / "01 每日简报" / today[:4] / today[5:7]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{today} PRIS 每日简报.md"
    focus = [item for item in assessments if item.tier == "focus"]
    quick = [item for item in assessments if item.tier == "quick"]
    lines = [
        "---", f"date: {today}", "type: pris-daily-brief", f"runner: {runner_id}", "---", "",
        f"# {today} PRIS 每日简报", "",
        "> 所有判断仅基于明确标注的元数据、摘要或全文。未读取全文时，不推测正文内容。", "",
        "## 今日重点", "",
    ]
    for index, item in enumerate(focus, 1):
        paper = papers[item.paper_id]
        is_economic_update = paper.field == "economics" and paper.source_type in {
            "institution_data", "institution_analysis", "institution_update"
        }
        section_title = "现实经济解读" if is_economic_update else "研究内容"
        question_label = "核心变化" if is_economic_update else "研究问题"
        background_label = "比较基准与背景" if is_economic_update else "背景与缺口"
        structure_label = "信息如何展开" if is_economic_update else "文章如何展开"
        method_label = "数据口径与证据来源" if is_economic_update else "方法/材料"
        contribution_label = "更新了什么判断" if is_economic_update else "核心贡献"
        lines.extend([
            f"### {index}. {paper.title}", "",
            f"- **领域/类型**：{paper.field} · {paper.source_type}",
            f"- **来源**：{paper.source}",
            f"- **作者**：{_authors(paper)}",
            f"- **日期**：{paper.published or '来源未提供'}",
            f"- **标识**：{_identifier(paper)}",
            f"- **核验**：{paper.verification_note}",
            f"- **原始页面**：[打开来源]({paper.url})",
            f"- **内容概览**：{item.one_sentence}",
            "", f"#### {section_title}", "",
            f"- **{question_label}**：{item.research_question}",
            f"- **{background_label}**：{item.background}",
            f"- **{structure_label}**：{item.article_structure}",
            f"- **为什么重要**：{item.why_important}",
            f"- **{method_label}**：{item.method}",
            f"- **必要的数学或技术核心**：{item.technical_core}",
            f"- **主要发现**：{item.main_findings}",
            f"- **{contribution_label}**：{item.contribution}",
            f"- **证据状态**：{item.evidence}",
            f"- **局限**：{item.limitations}",
            f"- **知识连接**：{item.connection}",
            f"- **阅读建议**：{item.reading_advice}",
            f"- **反馈指令**：`深读第{index}篇`", "",
        ])
    lines.extend(["## 快速动态", ""])
    for item in quick:
        paper = papers[item.paper_id]
        marker = f"DOI {paper.doi}" if paper.doi else paper.external_id
        lines.extend([
            f"- **[{paper.title}]({paper.url})**（{paper.source}；{marker or '标识缺失'}）  ",
            f"  {item.one_sentence}  ",
            f"  核验：{paper.verification_note}",
        ])
    if errors:
        lines.extend(["", "## 来源运行情况", ""])
        lines.extend(f"- ⚠️ {error}" for error in errors)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def add_featured_to_daily_report(vault: Path, paper: Paper, item: Assessment) -> Path:
    """Add or replace a manually selected full-text item in today's report."""
    today = date.today().isoformat()
    folder = vault / "01 每日简报" / today[:4] / today[5:7]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{today} PRIS 每日简报.md"
    if path.exists():
        body = path.read_text(encoding="utf-8")
    else:
        body = f"# {today} PRIS 每日简报\n\n"
    start = f"<!-- PRIS_FEATURED:{paper.id}:START -->"
    end = f"<!-- PRIS_FEATURED:{paper.id}:END -->"
    local_path = paper.raw.get("local_path", "")
    block = "\n".join([
        start,
        "## 人工精选补充",
        "",
        f"### {paper.title}",
        "",
        f"- **领域/类型**：{paper.field} · {paper.source_type}",
        f"- **来源**：{paper.source}",
        f"- **作者**：{_authors(paper)}",
        f"- **日期**：{paper.published or '来源未提供'}",
        f"- **标识**：{_identifier(paper)}",
        f"- **核验**：{paper.verification_note}",
        f"- **本地全文**：`{local_path}`",
        f"- **内容概览**：{item.one_sentence}",
        "",
        "#### 全文解读",
        "",
        f"- **研究问题**：{item.research_question}",
        f"- **背景与缺口**：{item.background}",
        f"- **文章如何展开**：{item.article_structure}",
        f"- **为什么重要**：{item.why_important}",
        f"- **方法/材料**：{item.method}",
        f"- **必要的数学或技术核心**：{item.technical_core}",
        f"- **主要发现**：{item.main_findings}",
        f"- **核心贡献**：{item.contribution}",
        f"- **证据状态**：{item.evidence}",
        f"- **局限**：{item.limitations}",
        f"- **知识连接**：{item.connection}",
        f"- **阅读建议**：{item.reading_advice}",
        "",
        end,
        "",
    ])
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.S)
    if pattern.search(body):
        body = pattern.sub(block.rstrip(), body)
    elif "## 今日重点" in body:
        body = body.replace("## 今日重点", block + "\n## 今日重点", 1)
    else:
        body = body.rstrip() + "\n\n" + block
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return path


def write_deep_read_stub(vault: Path, paper: Paper) -> Path:
    folder = vault / "02 深度阅读"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_name(paper.title)}.md"
    identifier = _identifier(paper)
    body = f"""---
type: pris-deep-read
status: waiting-for-full-text
paper_id: {paper.id}
---

# {paper.title}

## 已核验书目信息

- 作者：{', '.join(paper.authors) or '来源未提供'}
- 日期：{paper.published or '来源未提供'}
- 来源：{paper.source}
- {identifier}
- 原始页面：{paper.url}
- 核验结果：{paper.verification_note}

## 当前可确认内容

{paper.abstract or '来源没有提供摘要。'}

## 全文状态

尚未取得并读取全文。请使用 DOI 或主标识自行获取论文，然后将 PDF 放入约定目录或发送给系统。
在收到全文前，PRIS 不会编造研究方法、结果、稳健性检验或局限性。
"""
    path.write_text(body, encoding="utf-8")
    return path


def telegram_brief(papers: dict[str, Paper], assessments: list[Assessment]) -> str:
    today = date.today().isoformat()
    focus = [item for item in assessments if item.tier == "focus"]
    lines = [f"PRIS 每日简报｜{today}", ""]
    for index, item in enumerate(focus, 1):
        paper = papers[item.paper_id]
        question_label = "核心变化" if paper.field == "economics" and paper.source_type in {
            "institution_data", "institution_analysis", "institution_update"
        } else "研究问题"
        identifier = f"DOI: {paper.doi}" if paper.doi else paper.external_id
        lines.extend([
            f"{index}. {paper.title}",
            f"{item.one_sentence}",
            f"{question_label}：{item.research_question}",
            f"主要发现：{item.main_findings}",
            f"为什么值得看：{item.why_important}",
            f"{identifier or '未提供主标识'}｜{paper.verification_note}",
            paper.url,
            "",
        ])
    lines.append("回复“深读第2篇”即可加入深度阅读队列；其他自然语言评价也会被记录。")
    return "\n".join(lines)
