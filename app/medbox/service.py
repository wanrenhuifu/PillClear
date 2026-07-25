"""药箱服务层：CRUD + 药箱检查（D4，不依赖 Web 框架）。

分离两类职责：
- MedboxService：药箱持久化 CRUD（注入 UserMedboxRepository）
- check_medbox()：无状态药箱安全检查（注入 RuleSet + DrugRepository）

编排两个确定性部件：app/medbox/calculator.py 的成分叠加纯函数
与 app/rules/engine.py 的规则解释器。本层不做任何药学判断（铁律 #1）。
"""

from __future__ import annotations

from app.knowledge.repository import DrugReader
from app.knowledge.schemas import Ingredient
from app.medbox.calculator import check_overlap
from app.medbox.repository import UserMedboxRepository
from app.medbox.schemas import CheckReport, Medbox, MedboxItem
from app.rules.engine import match_and_render
from app.rules.schemas import RuleSet


class MedboxService:
    """药箱持久化 CRUD 服务。

    每个实例绑定一个 UserMedboxRepository，同一 device 的读写操作共享。
    """

    def __init__(self, user_repo: UserMedboxRepository) -> None:
        self._user_repo = user_repo

    def get_medbox(self, device_id: str) -> Medbox:
        """获取用户保存的药箱，无记录则返回空 Medbox。"""
        user_id = self._user_repo.get_or_create_user(device_id)
        return Medbox(
            items=[
                MedboxItem(
                    drug_id=row["drug_id"],
                    brand_name=row["brand_name"],
                    dosage_per_day=row["dosage_per_day"],
                )
                for row in self._user_repo.get_items(user_id)
            ]
        )

    def add_to_medbox(self, device_id: str, item: MedboxItem) -> Medbox:
        """添加/更新一个药品到药箱，返回完整药箱。"""
        user_id = self._user_repo.get_or_create_user(device_id)
        self._user_repo.upsert_item(user_id, item.drug_id, item.dosage_per_day)
        return self.get_medbox(device_id)

    def remove_from_medbox(self, device_id: str, drug_id: int) -> Medbox:
        """从药箱移除一个药品，返回完整药箱。"""
        user_id = self._user_repo.get_or_create_user(device_id)
        self._user_repo.remove_item(user_id, drug_id)
        return self.get_medbox(device_id)


def add_item(medbox: Medbox, item: MedboxItem) -> Medbox:
    """纯函数：向药箱加一项（同 drug_id 已存在则替换，幂等）。"""
    kept = [i for i in medbox.items if i.drug_id != item.drug_id]
    return Medbox(items=[*kept, item])


def remove_item(medbox: Medbox, drug_id: int) -> Medbox:
    """纯函数：按 drug_id 移除（不存在则为原样副本，幂等）。"""
    return Medbox(items=[i for i in medbox.items if i.drug_id != drug_id])


def check_medbox(
    medbox: Medbox,
    rules: RuleSet,
    repo: DrugReader,
    lifestyle_substances: list[str] | None = None,
) -> CheckReport:
    """无状态药箱安全检查：成分叠加计算 + 规则匹配 → CheckReport。

    纯编排函数——注入 rules（规则集）和 repo（药品查询），
    不持有状态，不依赖 Web 框架。
    """
    # 1. 按 brand_name 解析成分；未入库药品明示为 unresolved（铁律 #4）。
    drugs_map: dict[int, list[Ingredient]] = {}
    resolved_items: list[MedboxItem] = []
    unresolved: list[str] = []
    for item in medbox.items:
        row = repo.get_drug_by_brand(item.brand_name)
        if row is None:
            unresolved.append(item.brand_name)
            continue
        drugs_map[item.drug_id] = [
            Ingredient.model_validate(d) for d in row.get("ingredients", [])
        ]
        resolved_items.append(item)

    # 2. 成分叠加纯函数（铁律 #1：代码计算，无 LLM）。
    #    check_overlap 内部先计算共享成分日总摄入量，再生成超限警告。
    overlap = check_overlap(resolved_items, drugs_map)
    totals_by_name = {t.name: t for t in overlap.overlapping}

    # 3. 规则匹配 + 模板渲染：match_and_render 一次性完成匹配与
    #    {count}/{total_mg} 填充（局部性：渲染逻辑全集于规则引擎）。
    flat: list[Ingredient] = []
    for item in resolved_items:
        seen: set[str] = set()
        for ing in drugs_map.get(item.drug_id, []):
            if ing.name in seen:
                continue
            seen.add(ing.name)
            flat.append(ing)
    totals_for_engine = {
        name: (len(t.sources), t.total_amount_mg)
        for name, t in totals_by_name.items()
    }
    triggered = match_and_render(
        rules,
        flat,
        lifestyle_substances,
        ingredient_totals=totals_for_engine,
    )

    return CheckReport(
        overlap=overlap,
        triggered_rules=triggered,
        unresolved_drugs=unresolved,
    )


__all__ = ["MedboxService", "check_medbox", "add_item", "remove_item"]
