# FamilyGraph 家谱管理系统-数据库课间实验版

## 摘要

为了完成《数据库系统》课程要求中的“能熟练使用数据库系统进行问题解决和方案设计”的大纲而建立的课间实验课却只剩下一周完成两周展示三周截止四周考试而紧急完成的家谱管理系统。参考老师在课上讲述的ppt知识点和提供的四个家谱管理网站设计以及大模型给出的设计建议由文末提及的贡献者还没完成并测试通过但是还没有展示。

## 结构设计

本系统设计的结构如下

```SQL
Person(					-- 个人表
    id PRIMARY KEY,		-- ID 作为主键
    first name,			-- 姓
    last name,			-- 名
    gender,				-- 性别
    birth_date,			-- 出生日期
    death_date			-- 死亡日期
)

Relationship(			-- 关系表
    id PRIMARY KEY,		-- ID 作为主键
    person1_id,			-- 人物1
    person2_id,			-- 人物2
    relation_type,		-- 关系类型
    confidence_score,	-- 置信度
    source				-- 信息来源
)

Event(					-- 事件表，记录与人相关的事件
    id PRIMARY KEY，	-- ID 作为主键
    type,				-- 事件类型
    date,				-- 发生日期
    location			-- 发生地点
)

Person_Event(			-- 人物事件表
    person_id,			-- 人物
    event_id,			-- 事件
    (person_id, event_id) PRIMARY KEY,
    role				-- 角色
)
```

该设计遵循第三范式`3NF`原则，即每个非主属性必须直接依赖于主键，不能存在传递依赖
后续会尝试将关系优化至`BCNF`范式，需着重处理

```

Relationsip(
	(person1_id, person2_id) -> relationship
)
Person_Event(
	event_id -> role
)
以解决非主键依赖关系

```

- 阶段一（当前）：根据实际情况抽象出表的结构
	让Person表专注于存储个人信息，而不是记录复杂的人际关系
	设计Relationship表用于存储人际关系，便于“以PersonA为中心的查询”和“以关系为筛选关系的查询”
	Event用于记录事件，现阶段处于仅记录的状态
	Person_Event记录了与之相关的人及其扮演角色，用于后续从事件推导人际关系
	当前任务为实现四张表的基本操作，以及实现简单的关系查询

## 使用方法

暂无

## 贡献者

Github： starlightThD