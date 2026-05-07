# FamilyGraph 家谱管理系统-数据库课间实验版

## 摘要

为了完成《数据库系统》课程要求中的“能熟练使用数据库系统进行问题解决和方案设计”的大纲而建立的课间实验课却只剩下一周完成两周展示三周截止四周考试而紧急完成的家谱管理系统。参考老师在课上讲述的ppt知识点和提供的四个家谱管理网站设计以及大模型给出的设计建议由文末提及的贡献者还没完成并测试通过但是还没有展示。

## 结构设计

本系统设计的结构如下

```SQL
-- 用户表
User (
    user_id,
    username,
    password_hash,
    email,
    is_admin            -- 是否管理员（仅管理员可写操作）
);

-- 族谱表
FamilyTree (
    tree_id,
    name,                -- 谱名
    surname,             -- 姓氏
    revision_date,       -- 修谱时间
    creator_id,          -- 创建用户
);

-- 成员表
Person(
    person_id PK,
    tree_id,
    name,
    gender,
    birth_date,
    death_date
)

-- 关系表（血缘 + 婚姻）
Relationship(
    person1_id,
    person2_id,
    rel_type ENUM('parent','spouse'),

    PRIMARY KEY(person1_id, person2_id, rel_type)
)
-- 性能优化表
KinshipClosure(
    ancestor_id,
    descendant_id,
    depth,

    PRIMARY KEY (ancestor_id, descendant_id)
)
```

该设计满足 `BCNF` 范式

## 使用方法（PostgreSQL 本地安装）

1. 本地安装 PostgreSQL（建议 14+），并确保 `psql`、`createdb` 可用。
2. 创建数据库：

```bash
createdb -U postgres fgdb
```

3. 导入表结构：

```bash
psql -U postgres -d fgdb -f init/FG.sql
```

可选：将某个用户设为管理员（仅管理员可新增/编辑/删除）

```sql
UPDATE "User" SET is_admin = TRUE WHERE username = '你的用户名';
```

4. 启动前端 demo：

```bash
cd frontend
pip install -r requirements.txt
python app.py
```

当前仓库已移除 MySQL 容器编排与 MySQL 专用配置，默认以本地 PostgreSQL 为目标数据库。

## 贡献者

Github：starlightThD
