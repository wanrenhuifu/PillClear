"""说明书文本解析：章节切分（纯函数）+ 元数据尽力抽取。"""

from __future__ import annotations

import re

from app.knowledge.schemas import DrugMetadata, ParsedSection

# 匹配 国标说明书 章节标题 【xxx】；标题必须出现在行首，
# 正文内的交叉引用（"详见【注意事项】"）与警示标记（"【警示】…"）
# 不会被误当章节而切碎父章节（引用必须为 chunk 内容的精确子串）。
_SECTION_RE = re.compile(r"^【([^】]+)】", re.M)


def split_sections(text: str) -> list[ParsedSection]:
    """按行首【章节名】切分说明书，返回有序章节列表。

    - 章节内容为该标题之后、下一标题之前的文本（首尾空白已去除）。
    - 首个【】之前的前言（若有）被忽略。
    - 正文内部的【xxx】不触发切分，章节句子保持完整。
    """

    matches = list(_SECTION_RE.finditer(text or ""))
    sections: list[ParsedSection] = []
    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections.append(ParsedSection(section=name, content=content))
    return sections


def _section_map(sections: list[ParsedSection]) -> dict[str, str]:
    return {s.section: s.content for s in sections}


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    if not m:
        return None
    value = m.group(1).strip()
    return value or None


# 元数据行的取值正则：冒号后只允许同行空白（[^\S\n]，含全角空格），
# 取值不得跨越换行（[^\n]+）——否则"通用名称：\n商品名称：泰诺"
# 会把下一行吞进通用名。
_GENERIC_NAME_RE = r"通用名称?[:：][^\S\n]*([^\n]+)"
_SPECIFICATION_RE = r"规[^\S\n]*格[:：][^\S\n]*([^\n]+)"
_DOSAGE_FORM_RE = r"剂[^\S\n]*型[:：][^\S\n]*([^\n]+)"


def extract_metadata(text: str, sections: list[ParsedSection]) -> DrugMetadata:
    """从说明书尽力解析元数据；解析不到的字段保持 None。"""

    smap = _section_map(sections)
    name_block = smap.get("药品名称", "")

    generic_name = _first(_GENERIC_NAME_RE, name_block) or _first(
        _GENERIC_NAME_RE, text
    )

    specification = smap.get("规格") or _first(_SPECIFICATION_RE, text)

    approval_number = smap.get("批准文号") or _first(
        r"(国药准字[A-Za-z0-9]+)", text
    )

    dosage_form = smap.get("剂型") or _first(_DOSAGE_FORM_RE, text)

    otc_category = None
    if re.search(r"甲类非处方药|OTC\s*甲", text):
        otc_category = "甲类"
    elif re.search(r"乙类非处方药|OTC\s*乙", text):
        otc_category = "乙类"

    def _clean(value: str | None) -> str | None:
        if not value:
            return None
        lines = value.strip().splitlines()
        if not lines:
            return None
        return lines[0].strip() or None

    return DrugMetadata(
        generic_name=_clean(generic_name),
        otc_category=otc_category,
        dosage_form=_clean(dosage_form),
        specification=_clean(specification),
        approval_number=_clean(approval_number),
    )
