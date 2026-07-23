"""药箱服务层：CRUD + 冲突检查编排（D4，不依赖 Web 框架）。

编排两个确定性部件：app/medbox/calculator.py 的成分叠加纯函数
与 app/rules/engine.py 的规则解释器。本层不做任何药学判断（铁律 #1）。
"""

from __future__ import annotations

from app.knowledge.repository import DrugRepository
from app.knowledge.schemas import Ingredient
from app.medbox.calculator import calculate_ingredient_totals, check_overlap
from app.medbox.repository import UserMedboxRepository
from app.medbox.schemas import ConflictReport, Medbox, MedboxItem
from app.rules.engine import check_conflicts, count_matches, format_warning
from app.rules.schemas import Rule, RuleSet


class MedboxService:
    """药箱业务逻辑：CRUD + 冲突检查编排。"""

    def __init__(
        self,
        rules: RuleSet,
        repo: DrugRepository,
        user_repo: UserMedboxRepository | None = None,
    ) -> None:
        self._rules = rules
        self._repo = repo
        # user_repo 可选：无状态冲突检测（/medbox/check）不需要它；
        # 持久化端点（get/add/remove_from_medbox）必须注入，否则抛 RuntimeError。
        self._user_repo = user_repo

    def _require_user_repo(self) -> UserMedboxRepository:
        if self._user_repo is None:
            raise RuntimeError("药箱持久化未配置：MedboxService 缺少 user_repo")
        return self._user_repo

    def get_medbox(self, device_id: str) -> Medbox:
        """获取用户保存的药箱，无记录则返回空 Medbox。"""
        user_repo = self._require_user_repo()
        user_id = user_repo.get_or_create_user(device_id)
        return Medbox(
            items=[
                MedboxItem(
                    drug_id=row["drug_id"],
                    brand_name=row["brand_name"],
                    dosage_per_day=row["dosage_per_day"],
                )
                for row in user_repo.get_items(user_id)
            ]
        )

    def add_to_medbox(self, device_id: str, item: MedboxItem) -> Medbox:
        """添加/更新一个药品到药箱，返回完整药箱。"""
        user_repo = self._require_user_repo()
        user_id = user_repo.get_or_create_user(device_id)
        user_repo.upsert_item(user_id, item.drug_id, item.dosage_per_day)
        return self.get_medbox(device_id)

    def remove_from_medbox(self, device_id: str, drug_id: int) -> Medbox:
        """从药箱移除一个药品，返回完整药箱。"""
        user_repo = self._require_user_repo()
        user_id = user_repo.get_or_create_user(device_id)
        user_repo.remove_item(user_id, drug_id)
        return self.get_medbox(device_id)

    def add_item(self, medbox: Medbox, item: MedboxItem) -> Medbox:
        """向药箱加一项：同 drug_id 已存在则替换（幂等）。"""
        kept = [i for i in medbox.items if i.drug_id != item.drug_id]
        return Medbox(items=[*kept, item])

    def remove_item(self, medbox: Medbox, drug_id: int) -> Medbox:
        """按 drug_id 移除（不存在则为原样副本，幂等）。"""
        return Medbox(items=[i for i in medbox.items if i.drug_id != drug_id])

    def check_conflicts(
        self,
        medbox: Medbox,
        lifestyle_substances: list[str] | None = None,
    ) -> ConflictReport:
        """编排：成分叠加计算 + 规则匹配 → ConflictReport。"""
        # 1. 按 brand_name 解析成分；未入库药品明示为 unresolved（铁律 #4）。
        drugs_map: dict[int, list[Ingredient]] = {}
        resolved_items: list[MedboxItem] = []
        unresolved: list[str] = []
        for item in medbox.items:
            row = self._repo.get_drug_by_brand(item.brand_name)
            if row is None:
                unresolved.append(item.brand_name)
                continue
            drugs_map[item.drug_id] = [
                Ingredient.model_validate(d) for d in row.get("ingredients", [])
            ]
            resolved_items.append(item)

        # 2. 成分叠加纯函数（铁律 #1：代码计算，无 LLM）。
        totals = calculate_ingredient_totals(resolved_items, drugs_map)
        overlap = check_overlap(totals)
        totals_by_name = {t.name: t for t in totals}

        # 3. 规则匹配：扁平成分列表 = 每条目每成分一条（同药两条算两份，
        #    与 calculator 的 ≥2 条目口径一致）；条目内成分名先去重，
        #    防止 LLM 重复输出让 min_count: 2 被单个药品独自满足。
        flat: list[Ingredient] = []
        for item in resolved_items:
            seen: set[str] = set()
            for ing in drugs_map.get(item.drug_id, []):
                if ing.name in seen:
                    continue
                seen.add(ing.name)
                flat.append(ing)
        triggered = [
            self._render(rule, flat, totals_by_name)
            for rule in check_conflicts(self._rules, flat, lifestyle_substances)
        ]

        return ConflictReport(
            overlap=overlap,
            triggered_rules=triggered,
            unresolved_drugs=unresolved,
        )

    def _render(
        self,
        rule: Rule,
        flat: list[Ingredient],
        totals_by_name: dict[str, object],
    ) -> Rule:
        """填充 warning 模板的 {count}/{total_mg}。

        必须 model_copy 出副本再改：get_rule_set 是 lru_cache 单例，
        就地修改会让一个请求的渲染结果串给后续所有请求。
        """
        count = 0
        total_mg: float | None = None
        if rule.conditions.ingredients:
            cond = rule.conditions.ingredients[0]
            total = totals_by_name.get(cond.name)
            if total is not None:
                count = len(total.sources)  # type: ignore[union-attr]
                total_mg = total.total_amount_mg  # type: ignore[union-attr]
            else:
                # 未被共享的成分没有叠加汇总 → 退化为命中条目数，总量「未知」
                count = count_matches(cond, flat)
        return rule.model_copy(
            update={"warning": format_warning(rule, count=count, total_mg=total_mg)}
        )


__all__ = ["MedboxService"]
