"""app.knowledge.parser 单元测试：章节切分无丢失 + 元数据抽取。"""

from app.knowledge.parser import extract_metadata, split_sections
from tests.conftest import SAMPLE_INSERT_FENBIDE, SAMPLE_INSERT_TAINUO

TAINUO_SECTIONS = [
    "药品名称", "成份", "适应症", "规格", "用法用量",
    "不良反应", "禁忌", "注意事项", "药物相互作用", "批准文号",
]
FENBIDE_SECTIONS = [
    "药品名称", "成份", "适应症", "用法用量",
    "不良反应", "禁忌", "注意事项", "药物相互作用",
]


def test_split_sections_names_and_count_tainuo():
    sections = split_sections(SAMPLE_INSERT_TAINUO)
    assert [s.section for s in sections] == TAINUO_SECTIONS


def test_split_sections_names_and_count_fenbide():
    sections = split_sections(SAMPLE_INSERT_FENBIDE)
    assert [s.section for s in sections] == FENBIDE_SECTIONS


def test_split_sections_no_content_loss():
    smap = {s.section: s.content for s in split_sections(SAMPLE_INSERT_TAINUO)}
    assert smap["用法用量"] == "口服。成人一次1-2片，一日3次。"
    assert smap["禁忌"] == "严重肝肾功能不全者禁用。"
    assert "对乙酰氨基酚325毫克" in smap["成份"]
    assert smap["批准文号"] == "国药准字H10920001"
    # 每个章节内容非空
    assert all(v.strip() for v in smap.values())


def test_extract_metadata_tainuo():
    sections = split_sections(SAMPLE_INSERT_TAINUO)
    meta = extract_metadata(SAMPLE_INSERT_TAINUO, sections)
    assert meta.generic_name == "酚麻美敏片"
    assert meta.specification == "复方"
    assert meta.approval_number == "国药准字H10920001"


def test_extract_metadata_missing_fields_are_none():
    sections = split_sections(SAMPLE_INSERT_FENBIDE)
    meta = extract_metadata(SAMPLE_INSERT_FENBIDE, sections)
    assert meta.generic_name == "布洛芬缓释胶囊"
    # 芬必得样例无【批准文号】章节且无国药准字串 → None
    assert meta.approval_number is None
    assert meta.otc_category is None


def test_extract_metadata_blank_value_no_crash():
    # 冒号后只有空白（OCR/残缺说明书）：_first 不得回传 ""，_clean 不得 IndexError
    text = "【成份】\n布洛芬\n规格： "
    sections = split_sections(text)
    meta = extract_metadata(text, sections)
    assert meta.specification is None


def test_generic_name_does_not_bleed_into_next_line():
    # 通用名值缺失时，正则不得跨越换行吞掉下一行（商品名行）
    text = "【药品名称】\n通用名称：\n商品名称：泰诺\n【成份】\n对乙酰氨基酚"
    sections = split_sections(text)
    meta = extract_metadata(text, sections)
    assert meta.generic_name is None


def test_inline_brackets_do_not_split_section():
    # 正文内的【xxx】（交叉引用/警示标记）不是章节标题，不得切碎父章节
    text = "【注意事项】\n详见【成份】章节，长期饮酒者慎用。\n【禁忌】\n禁用。"
    sections = split_sections(text)
    assert [s.section for s in sections] == ["注意事项", "禁忌"]
    assert sections[0].content == "详见【成份】章节，长期饮酒者慎用。"
