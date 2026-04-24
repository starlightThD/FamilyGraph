# FamilyGraph 家谱管理系统-数据库课间实验版

## 摘要

为了完成《数据库系统》课程要求中的“能熟练使用数据库系统进行问题解决和方案设计”的大纲而建立的课间实验课却只剩下一周完成两周展示三周截止四周考试而紧急完成的家谱管理系统。参考老师在课上讲述的ppt知识点和提供的四个家谱管理网站设计以及大模型给出的设计建议由文末提及的贡献者还没完成并测试通过但是还没有展示。

## 结构设计

本系统设计的结构如下

```SQL
Person(					-- 个人表
    person_id PRIMARY KEY,	-- ID 作为主键
    first name,			-- 姓
    last name,			-- 名
    gender,				-- 性别
    birth_date,			-- 出生日期
    death_date			-- 死亡日期
)
person_id -> first name, last name, gender, birth_date, death_date


Event(					-- 事件表
    event_id PRIMARY KEY，	-- ID 作为主键
    type,				-- 事件类型
    start_date,			-- 发生日期
	end_date,			-- 结束日期
    confidence_score,	-- 置信度
    source				-- 信息来源
)
id -> type, start_date, end_date, confidence_score, source

Person_Event(
    person_id,			-- 人物
    event_id,			-- 事件
	role				-- 身份
)
(person_id, event_id) -> role
-- 到此三张表，保证BCNF，但是根据关系查找人会很慢（如查找A的儿子，需要先找到决定A是父亲的事件，在根据事件找到被决定为儿子的人）

-- 待选，用于读优化
Relationship(
    rel_id PRIMARY KEY,
    person1_id,
    person2_id,
    relationship_type,
    start_date,
    end_date,
    event_id
)
-- 需软约束person1和person2的顺序，如年长在前，男性在前，以提查询效率

```

该设计遵循`BCNF`原则

- 阶段一（当前）：根据实际情况抽象出表的结构
	让Person表专注于存储个人信息，而不是记录复杂的人际关系
	Event用于记录事件，现阶段处于仅记录的状态
	Person_Event通过事件来决定人的身份，确保身份可辨识和唯一存储

	可能补充设计Relationship表用于存储人际关系，便于“以PersonA为中心的查询”和“以关系为筛选关系的查询”

## 使用方法

暂无

## 贡献者

Github： starlightThD
