根据主键，外键，约束得出如下的语句

```SQL

-- 启用外键约束（每次连接后执行）
PRAGMA foreign_keys = ON;

-- 1. 人物表
CREATE TABLE Person (
    person_id   INTEGER PRIMARY KEY,                     -- 主键
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    gender      TEXT NOT NULL CHECK (gender IN ('M', 'F', 'Other')),
    birth_date  TEXT,                                    -- 使用 ISO 格式 'YYYY-MM-DD'
    death_date  TEXT,
    CHECK (birth_date IS NULL OR death_date IS NULL OR birth_date < death_date)
);

-- 2. 事件表
CREATE TABLE Event (
    event_id         INTEGER PRIMARY KEY,
    type             TEXT NOT NULL CHECK (type IN ('birth', 'marriage', 'death', 'divorce', 'custom')),
    start_date       TEXT NOT NULL,
    end_date         TEXT,
    confidence_score REAL CHECK (confidence_score BETWEEN 0 AND 1),
    source           TEXT
);

-- 3. 人物-事件关联表
CREATE TABLE Person_Event (
    person_id INTEGER NOT NULL,
    event_id  INTEGER NOT NULL,
    role      TEXT NOT NULL,
    PRIMARY KEY (person_id, event_id),                  -- 复合主键
    FOREIGN KEY (person_id) REFERENCES Person(person_id) ON DELETE CASCADE,
    FOREIGN KEY (event_id)  REFERENCES Event(event_id)  ON DELETE CASCADE
);

-- 4. 关系表（读优化冗余表）
CREATE TABLE Relationship (
    rel_id            INTEGER PRIMARY KEY,
    person1_id        INTEGER NOT NULL,
    person2_id        INTEGER NOT NULL,
    relationship_type TEXT NOT NULL CHECK (relationship_type IN ('parent', 'child', 'spouse', 'sibling', 'other')),
    start_date        TEXT,
    end_date          TEXT,
    event_id          INTEGER,
    FOREIGN KEY (person1_id) REFERENCES Person(person_id) ON DELETE RESTRICT,
    FOREIGN KEY (person2_id) REFERENCES Person(person_id) ON DELETE RESTRICT,
    FOREIGN KEY (event_id)   REFERENCES Event(event_id)   ON DELETE SET NULL,
    CHECK (person1_id != person2_id)                     -- 不允许自指
);

-- 5. 索引（读优化）
CREATE INDEX idx_person_names ON Person(last_name, first_name);
CREATE INDEX idx_person_birth ON Person(birth_date);

CREATE INDEX idx_event_type_start ON Event(type, start_date);
CREATE INDEX idx_event_confidence ON Event(confidence_score DESC);

CREATE INDEX idx_pe_event_role ON Person_Event(event_id, role);
CREATE INDEX idx_pe_person_role ON Person_Event(person_id, role);

CREATE INDEX idx_rel_p1_type ON Relationship(person1_id, relationship_type);
CREATE INDEX idx_rel_p2_type ON Relationship(person2_id, relationship_type);
CREATE INDEX idx_rel_dates ON Relationship(start_date, end_date);
CREATE INDEX idx_rel_event ON Relationship(event_id);

-- 可选：防止同一对人、同类型、同一事件重复（唯一索引部分条件）
CREATE UNIQUE INDEX uniq_rel_same_event ON Relationship (
    MIN(person1_id, person2_id),
    MAX(person1_id, person2_id),
    relationship_type,
    event_id
) WHERE event_id IS NOT NULL;

```