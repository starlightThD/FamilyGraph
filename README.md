# FamilyGraph 家谱管理系统-数据库课间实验版

## 摘要

为了完成《数据库系统》课程要求中的“能熟练使用数据库系统进行问题解决和方案设计”的大纲而建立的课间实验课却只剩下一周完成两周展示三周截止四周考试而紧急完成的家谱管理系统。参考老师在课上讲述的ppt知识点和提供的四个家谱管理网站设计以及大模型给出的设计建议由文末提及的贡献者还没完成并测试通过但是还没有展示。

## 结构设计

本系统设计的结构如下

```SQL
-- 用户表
CREATE TABLE User (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE,
    password_hash VARCHAR(255),
    email VARCHAR(100)
);

-- 族谱表
CREATE TABLE FamilyTree (
    tree_id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,        -- 谱名
    surname VARCHAR(50) NOT NULL,      -- 姓氏
    revision_date DATE,                -- 修谱时间
    creator_id INT NOT NULL,           -- 创建用户
    FOREIGN KEY (creator_id) REFERENCES User(user_id)
);

-- 成员表
CREATE TABLE Person (
    person_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    tree_id INT NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),              -- 姓氏可冗余，也可从族谱继承
    gender CHAR(1) CHECK (gender IN ('M','F')),
    birth_date DATE,
    death_date DATE,
    biography TEXT,                     -- 生平简介
    generation INT NOT NULL,            -- 辈分（从始祖0开始）
    FOREIGN KEY (tree_id) REFERENCES FamilyTree(tree_id),
    INDEX idx_tree_gen (tree_id, generation),
    INDEX idx_name (last_name, first_name)
);

-- 关系表（血缘 + 婚姻）
CREATE TABLE Relationship (
    rel_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    person1_id BIGINT NOT NULL,         -- 长辈/夫/一方
    person2_id BIGINT NOT NULL,         -- 晚辈/妻/另一方
    rel_type ENUM('father','mother','child','husband','wife','other') NOT NULL,
    start_date DATE,                    -- 婚姻开始/关系生效
    end_date DATE,                      -- 离婚/关系结束
    FOREIGN KEY (person1_id) REFERENCES Person(person_id),
    FOREIGN KEY (person2_id) REFERENCES Person(person_id),
    INDEX idx_p1_type (person1_id, rel_type),
    INDEX idx_p2_type (person2_id, rel_type),
    UNIQUE KEY uk_pair (person1_id, person2_id, rel_type)
);

```

该设计满足`BCNF`范式
		
## 使用方法

暂无

## 贡献者

Github： starlightThD
