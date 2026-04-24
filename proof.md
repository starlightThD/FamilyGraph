## BCNF 范式证明

给定以下三张表的设计：

- **Person**(`person_id` PRIMARY KEY, `first_name`, `last_name`, `gender`, `birth_date`, `death_date`)
- **Event**(`event_id` PRIMARY KEY, `type`, `start_date`, `end_date`, `confidence_score`, `source`)
- **Person_Event**(`person_id`, `event_id`, `role`)，其中 `(person_id, event_id)` 是主键，且 `(person_id, event_id) → role`

### 1. Person 表

**候选键**：`{person_id}`（主键）

**可能的函数依赖**（基于实际语义，不引入额外唯一性约束）：
- `{person_id} → {first_name, last_name, gender, birth_date, death_date}`（由主键定义）
- 不存在其他非平凡函数依赖，因为 `first_name`、`last_name` 等属性单独或组合均不保证唯一性，且没有其他属性决定 `person_id`。

**BCNF 检查**：  
所有非平凡函数依赖的左部必须包含候选键。此处唯一的非平凡 FD 左部为 `{person_id}`，它是超键，因此 **Person 满足 BCNF**。

### 2. Event 表

**候选键**：`{event_id}`（主键）

**可能的函数依赖**：
- `{event_id} → {type, start_date, end_date, confidence_score, source}`（主键定义）
- 无其他非平凡 FD（例如 `type` 不唯一，`start_date` 等不决定 event_id）。

**BCNF 检查**：  
所有非平凡 FD 的左部 `{event_id}` 是超键，因此 **Event 满足 BCNF**。

### 3. Person_Event 表

**候选键**：`{person_id, event_id}`（复合主键）

**可能的函数依赖**：
- `{person_id, event_id} → {role}`（主键定义）
- 是否存在其他非平凡 FD？  
  - `{person_id} → {role}`？不成立，因为同一人可参与多个事件且角色可能不同。  
  - `{event_id} → {role}`？不成立，因为同一事件中不同人可扮演不同角色。  
  - `{person_id, role} → {event_id}`？无业务规则保证，通常不成立。  
  - 其他组合同理不产生新的 FD。

**BCNF 检查**：  
唯一非平凡 FD 的左部 `{person_id, event_id}` 正是候选键，因此是超键。**Person_Event 满足 BCNF**。

### 结论

三张表均不存在任何违反 BCNF 的非平凡函数依赖，故 **该数据库设计（Person、Event、Person_Event）符合 BCNF 范式**。

## 补充：包含第四张表 `Relationship` 后的 BCNF 结论

若在原有三张表（`Person`、`Event`、`Person_Event`）的基础上，增加第四张表：

**Relationship**(  
 `rel_id` PRIMARY KEY,  
 `person1_id`,  
 `person2_id`,  
 `relationship_type`,  
 `start_date`,  
 `end_date`,  
 `event_id`  
)

### 1. 候选键与函数依赖分析

- **显式候选键**：`{rel_id}`（主键）。
- **可能的其他候选键**：  
  由于表中允许同一对人物在不同事件、不同时间段存在多条关系记录，且没有声明 `(person1_id, person2_id, relationship_type, start_date, end_date, event_id)` 的唯一性约束，因此 **不存在其他候选键**。
- **非平凡函数依赖**：  
  按照关系数据库设计的基本假设，该表唯一确定的函数依赖是：  
  `{rel_id} → {person1_id, person2_id, relationship_type, start_date, end_date, event_id}`  
  不存在其他非平凡函数依赖（例如 `{person1_id, person2_id} → relationship_type` 不成立，因为同一对人可有多条不同时间或不同事件的关系记录）。

### 2. BCNF 判定

BCNF 要求：对于每一个非平凡函数依赖 `X → Y`，`X` 必须包含一个候选键。  
此处唯一的非平凡 FD 的左部为 `{rel_id}`，而 `{rel_id}` 正是候选键，因此该依赖满足 BCNF 条件。  
**没有其他非平凡 FD** 存在，故 **`Relationship` 表符合 BCNF**。

### 3. 包含四张表的总体结论

- `Person`：BCNF ✅  
- `Event`：BCNF ✅  
- `Person_Event`：BCNF ✅  
- `Relationship`：BCNF ✅  

**最终结论**：在仅依赖主键约束且未引入额外函数依赖（如隐含的唯一性约束）的前提下，**包含 `Relationship` 表在内的整个家族图谱数据库设计依然符合 BCNF 范式**。