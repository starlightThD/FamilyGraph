# 数据库模式 BCNF 范式证明

本数据库包含以下五个关系模式

1. **User**(user_id, username, password_hash, email)  
2. **FamilyTree**(tree_id, name, surname, revision_date, creator_id)  
3. **Person**(person_id, tree_id, name, gender, birth_date, death_date)  
4. **Relationship**(person1_id, person2_id, rel_type)  
5. **KinshipClosure**(ancestor_id, descendant_id, depth)

## 1. 基本假设与函数依赖语义

- 每个表的主键（下划线标注）是唯一候选键，且所有非键属性**完全函数依赖**于主键。
- 不存在其他非平凡的函数依赖，除非由主键依赖派生或由业务唯一性约束引起（例如 `username` 唯一，此时 `username → user_id` 也成立，但我们会显式处理）。
- 外键约束（如 `FamilyTree.creator_id` 引用 `User.user_id`）不影响 BCNF 判定，因为外键不是函数依赖的决定因素。

## 2. 各关系模式的 BCNF 证明

### 2.1 `User` 表
- **候选键**：`{user_id}`（主键）。  
  若 `username` 在业务上唯一，则 `{username}` 也是候选键。为严格证明，分两种情况：
  - **情况 A**（仅 `user_id` 为候选键）：  
    所有非平凡函数依赖的决定因素必须包含 `user_id`，否则无法决定其他属性。例如 `username → email` 不成立（除非 `username` 唯一，但此时它成为候选键，见情况 B）。  
    因此 `F⁺` 中所有非平凡依赖的左边都是超键 → 满足 BCNF。
  - **情况 B**（`username` 也是候选键）：  
    若 `username` 唯一，则存在 `username → user_id` 及 `username → {password_hash, email}`。此时 `username` 是候选键，任何包含 `username` 或 `user_id` 的属性集都是超键。  
    可能存在的其他依赖如 `email → user_id` 若成立（`email` 唯一），则 `email` 也成为候选键，需确保 `email` 被声明为唯一。实践中，典型设计会保证所有候选键都被明确约束。  
    由于我们只考虑设计者实际声明的依赖，且通常 `user_id` 为主键，其余属性无额外非平凡依赖，因此满足 BCNF。

### 2.2 `FamilyTree` 表
- **候选键**：`{tree_id}`（主键）。  
  非键属性：`name`, `surname`, `revision_date`, `creator_id`。  
  函数依赖仅有：`{tree_id} → {name, surname, revision_date, creator_id}`。  
  任何非平凡依赖的左边必须包含 `tree_id`，否则无法推出其他属性（例如 `creator_id → ...` 不成立，因为一个用户可以创建多个族谱）。  
  因此所有非平凡依赖的决定因素都是超键 → 满足 BCNF。

### 2.3 `Person` 表
- **候选键**：`{person_id}`（主键）。  
  非键属性：`tree_id`, `name`, `gender`, `birth_date`, `death_date`。  
  函数依赖仅有：`{person_id} → {tree_id, name, gender, birth_date, death_date}`。  
  无其他非平凡依赖（例如 `tree_id → name` 不成立，因为一个族谱包含多人）。  
  因此满足 BCNF。

### 2.4 `Relationship` 表
- 属性：`person1_id`, `person2_id`, `rel_type`。  
- **候选键**：`(person1_id, person2_id, rel_type)`（复合主键）。  
- 该表没有非键属性，因此**不存在任何非平凡的函数依赖**（非平凡依赖要求右边属性不在左边，但此处所有属性都在左边）。  
- 平凡依赖（如 `(person1_id, person2_id, rel_type) → person1_id`）不需要检查。  
- 根据 BCNF 定义，没有非平凡依赖的关系模式自动满足 BCNF。

### 2.5 `KinshipClosure` 表
- 属性：`ancestor_id`, `descendant_id`, `depth`。  
- **候选键**：`(ancestor_id, descendant_id)`（复合主键）。  
- 函数依赖：`{ancestor_id, descendant_id} → depth`。  
  不存在其他非平凡依赖（如 `ancestor_id → descendant_id` 不成立，`depth → ...` 不成立）。  
- 所有非平凡依赖的决定因素 `{ancestor_id, descendant_id}` 正是候选键，因此是超键 → 满足 BCNF。

## 3. 整体结论

- **User**、**FamilyTree**、**Person**、**Relationship**、**KinshipClosure** 均满足 BCNF 的定义。  
- 因此，**整个数据库模式属于 BCNF 范式**。
