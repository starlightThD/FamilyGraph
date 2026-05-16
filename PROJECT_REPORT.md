# FamilyGraph 项目阶段汇报（当前仓库代码核对版）

> 核对时间：2026-05-14  
> 核对范围：`application/`、`data/`、`init/`、`graph/`、`README.md`、`proof.md`

## 1. 总体结论

项目主体功能已完成，尤其是登录注册、族谱/成员管理、邀请协作、树形预览、祖先查询、亲缘路径查询、数据生成与导入导出均已落地。  
除“物理优化实验材料”外，其余内容已补齐为可直接用于课程汇报/答辩的版本（含单条 SQL 与跨表约束实现说明）。

## 2. 需求完成度总览

| 模块 | 要求 | 状态 | 说明 |
|---|---|---|---|
| 功能实现 | 登录后仅可访问自己创建或受邀族谱 | ✅ 已实现 | 基于 `tree_access_mask` 与邀请表控制访问 |
| 功能实现 | 用户注册 | ✅ 已实现 | 注册接口与密码哈希逻辑已存在 |
| 功能实现 | Dashboard 总人数/男女比例 | ✅ 已实现 | Dashboard 统计逻辑已存在 |
| 功能实现 | 族谱与成员 CRUD | ✅ 已实现 | 族谱、成员增删改查接口齐全 |
| 功能实现 | 族谱邀请协作 | ✅ 已实现 | `FamilyTreeInvite` + 邀请处理逻辑 |
| 功能实现 | 成员姓名模糊查询 | ✅ 已实现 | 使用 `ILIKE` 查询 |
| 功能实现 | 树形预览（层级关系） | ✅ 已实现 | 树预览页面 + 节点展开接口 |
| 功能实现 | 人物祖先查询（树状展示） | ✅ 已实现 | 递归 CTE 查询祖先并可视化 |
| 功能实现 | 两人亲缘路径查询 | ✅ 已实现 | 路径查询逻辑已存在 |
| 建模规范化 | ER 图 | ✅ 已实现 | `graph/E-R.png` |
| 建模规范化 | 关系模式与范式说明 | ✅ 已实现 | `proof.md` 提供 BCNF 证明 |
| 建模规范化 | PK/FK/CHECK 约束 | ✅ 已补充说明 | PK/FK/CHECK 已落地；跨表约束用触发器方案补充（见第 5 节） |
| 数据工程 | 10 个族谱 | ✅ 已实现 | 数据脚本固定 10 个姓氏家族 |
| 数据工程 | 至少 1 个族谱 >50,000 人 | ✅ 已实现 | `TARGET_PER_TREE = 50000`（高复杂族谱） |
| 数据工程 | 全系统 >=100,000 人 | ✅ 已实现 | 设计目标总量已超过 100,000 |
| 数据工程 | 每人至少有亲缘关系 | ✅ 已实现 | 生成逻辑会生成 parent/spouse 关系 |
| 数据工程 | 单族谱至少 30 代 | ✅ 已实现 | 默认 `gen_count = 30` |
| 数据工程 | CSV 批量导入（COPY/LOAD DATA） | ✅ 已实现 | `load_csv.py` 使用 PostgreSQL `COPY` |
| 数据工程 | 导出某分支备份 | ✅ 已实现 | 已实现按族谱导出 ZIP/CSV |
| SQL 核心 | 成员ID查配偶+子女（单 SQL） | ✅ 已补充 | 单条 SQL 版本已整理（见第 5 节） |
| SQL 核心 | 递归 CTE 查祖先 | ✅ 已实现 | 单条递归 CTE |
| SQL 核心 | 平均寿命最长辈分 | ✅ 已实现 | SQL 统计逻辑已存在 |
| SQL 核心 | 男性>50且无配偶 | ✅ 已补充 | 固定条件单条 SQL 已整理（见第 5 节） |
| SQL 核心 | 早于本代平均出生年份成员 | ✅ 已实现 | SQL 已实现 |
| 物理优化 | 祖先/亲缘递归查询索引策略 | ✅ 已实现 | `init/FG.sql` 已新增 `idx_rel_parent_person2_person1` |
| 物理优化 | 索引动机与适配查询说明 | ✅ 已补充 | 针对 `person2_id -> person1_id` 递归方向优化 |
| 物理优化 | 有/无索引性能对比 + EXPLAIN | ⏳ 进行中 | 索引已落地，待补完整实验截图与计划输出 |

## 3. 关键实现证据（文件定位）

- 后端主逻辑：`application/app.py`
- 数据库结构：`init/FG.sql`
- 数据生成：`data/generate.py`
- CSV 导入：`application/load_csv.py`
- ER 图：`graph/E-R.png`
- BCNF 说明：`proof.md`

## 4. 当前最需要补齐的内容（仅优化项，建议优先级）

1. **P0：补齐 EXPLAIN 对比实验结果**  
   现已完成索引 DDL 落地，下一步补充“建索引前后”的 `EXPLAIN (ANALYZE, BUFFERS)` 截图与统计表。

## 5. 物理优化补充（可直接放入报告）

### 5.1 递归查询索引优化（已落地）

#### 场景

- 查询一个人的所有直系祖先；
- 查询两个人之间是否有亲缘关系（递归向上找共同祖先）。

上述两类查询在递归过程中都会高频执行：

```sql
WHERE r.rel_type = 'parent'
  AND r.person2_id = ?
```

并读取 `person1_id` 作为下一层父节点。

#### 索引 DDL

```sql
CREATE INDEX IF NOT EXISTS idx_rel_parent_person2_person1
ON "Relationship" (person2_id, person1_id)
WHERE rel_type = 'parent';
```

#### 设计理由

- 现有主键为 `(person1_id, person2_id, rel_type)`，对 `person2_id` 方向查询不友好；
- 祖先/亲缘递归是“子找父”（`person2_id -> person1_id`），与主键顺序不一致；
- 该部分索引仅覆盖 `rel_type='parent'` 记录，体积更小、命中更集中。

#### 预期效果

- 祖先查询中每层递归对 `Relationship` 的扫描行数显著减少；
- 两人亲缘关系判定时，双向递归的层级扩展成本下降；
- 执行计划更容易从 `Seq Scan` 转为 `Index Scan` / `Bitmap Index Scan`。

### 5.2 建议的对比验证 SQL（待补实验截图）

```sql
EXPLAIN (ANALYZE, BUFFERS)
WITH RECURSIVE ancestor_walk AS (
    SELECT r.person1_id AS ancestor_id, 1 AS depth, ARRAY[r.person2_id, r.person1_id] AS path
    FROM "Relationship" r
    WHERE r.rel_type = 'parent' AND r.person2_id = 15240
    UNION ALL
    SELECT r.person1_id, aw.depth + 1, aw.path || r.person1_id
    FROM ancestor_walk aw
    JOIN "Relationship" r
      ON r.rel_type = 'parent'
     AND r.person2_id = aw.ancestor_id
    WHERE NOT (r.person1_id = ANY(aw.path))
)
SELECT ancestor_id, MIN(depth) AS depth
FROM ancestor_walk
GROUP BY ancestor_id;
```

```sql
EXPLAIN (ANALYZE, BUFFERS)
WITH RECURSIVE from_walk AS (
    SELECT 15240::INTEGER AS current_id, ARRAY[15240::INTEGER] AS path, 0 AS depth
    UNION ALL
    SELECT r.person1_id, fw.path || r.person1_id, fw.depth + 1
    FROM from_walk fw
    JOIN "Relationship" r
      ON r.rel_type = 'parent'
     AND r.person2_id = fw.current_id
    WHERE NOT (r.person1_id = ANY(fw.path))
),
to_walk AS (
    SELECT 18001::INTEGER AS current_id, ARRAY[18001::INTEGER] AS path, 0 AS depth
    UNION ALL
    SELECT r.person1_id, tw.path || r.person1_id, tw.depth + 1
    FROM to_walk tw
    JOIN "Relationship" r
      ON r.rel_type = 'parent'
     AND r.person2_id = tw.current_id
    WHERE NOT (r.person1_id = ANY(tw.path))
)
SELECT 1
FROM from_walk f
JOIN to_walk t ON t.current_id = f.current_id
LIMIT 1;
```

## 6. 非优化部分补充（可直接放入报告）

### 6.1 成员 ID 查询“配偶 + 子女”的单条 SQL

```sql
SELECT relation_type, related_id, related_name
FROM (
    -- 配偶
    SELECT
        'spouse' AS relation_type,
        CASE
            WHEN r.person1_id = %(person_id)s THEN r.person2_id
            ELSE r.person1_id
        END AS related_id,
        p2.name AS related_name
    FROM "Relationship" r
    JOIN "Person" p2
      ON p2.person_id = CASE
            WHEN r.person1_id = %(person_id)s THEN r.person2_id
            ELSE r.person1_id
         END
    WHERE r.rel_type = 'spouse'
      AND %(person_id)s IN (r.person1_id, r.person2_id)

    UNION ALL

    -- 子女
    SELECT
        'child' AS relation_type,
        c.person_id AS related_id,
        c.name AS related_name
    FROM "Relationship" r
    JOIN "Person" c ON c.person_id = r.person2_id
    WHERE r.rel_type = 'parent'
      AND r.person1_id = %(person_id)s
) t
ORDER BY relation_type, related_id;
```

### 6.2 “男性 > 50 岁且无配偶”的单条 SQL

```sql
SELECT
    p.person_id,
    p.name,
    EXTRACT(YEAR FROM age(COALESCE(p.death_date, CURRENT_DATE), p.birth_date)) AS age_years
FROM "Person" p
WHERE p.gender = 'male'
  AND p.birth_date IS NOT NULL
  AND EXTRACT(YEAR FROM age(COALESCE(p.death_date, CURRENT_DATE), p.birth_date)) > 50
  AND NOT EXISTS (
      SELECT 1
      FROM "Relationship" r
      WHERE r.rel_type = 'spouse'
        AND (r.person1_id = p.person_id OR r.person2_id = p.person_id)
  )
ORDER BY p.person_id;
```

### 6.3 “父辈出生早于子代”的跨表约束实现（触发器）

> 说明：该规则涉及跨表比较，`CHECK` 约束不适合直接表达，采用触发器更稳妥。

```sql
CREATE OR REPLACE FUNCTION fg_check_parent_birth_before_child()
RETURNS TRIGGER AS $$
DECLARE
    parent_birth DATE;
    child_birth  DATE;
BEGIN
    IF NEW.rel_type <> 'parent' THEN
        RETURN NEW;
    END IF;

    SELECT birth_date INTO parent_birth
    FROM "Person"
    WHERE person_id = NEW.person1_id;

    SELECT birth_date INTO child_birth
    FROM "Person"
    WHERE person_id = NEW.person2_id;

    IF parent_birth IS NOT NULL
       AND child_birth IS NOT NULL
       AND parent_birth >= child_birth THEN
        RAISE EXCEPTION
            'Invalid parent relation: parent(%) birth_date % must be earlier than child(%) birth_date %',
            NEW.person1_id, parent_birth, NEW.person2_id, child_birth;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_parent_birth_before_child ON "Relationship";

CREATE TRIGGER trg_check_parent_birth_before_child
BEFORE INSERT OR UPDATE ON "Relationship"
FOR EACH ROW
EXECUTE FUNCTION fg_check_parent_birth_before_child();
```

## 7. 可直接放进答辩/提交材料的描述

- 本项目已实现课程要求中的主要业务功能与核心 SQL 递归能力，具备可演示的完整流程（注册/登录->族谱协作->成员管理->树形与查询分析）。  
- 在数据库建模方面，已完成 ER 图、关系模式映射及 BCNF 证明。  
- 在数据工程方面，已提供大规模模拟数据生成（10 个族谱、30 代传承、总量超过 10 万）及 COPY 导入、族谱级导出。  
- 当前优化工作已进入“实验结果补全”阶段，索引策略已落地，待补 EXPLAIN 前后对比截图与统计表。
