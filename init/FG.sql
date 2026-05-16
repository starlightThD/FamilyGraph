-- FamilyGraph PostgreSQL schema
-- Usage example:
--   createdb -U postgres fgdb
--   psql -U postgres -d fgdb -f init/FG.sql

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'gender_type') THEN
        CREATE TYPE gender_type AS ENUM ('male', 'female', 'other');
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rel_type_enum') THEN
        CREATE TYPE rel_type_enum AS ENUM ('parent', 'spouse');
    END IF;
END
$$;

DROP TABLE IF EXISTS "KinshipClosure" CASCADE;

CREATE TABLE IF NOT EXISTS "User" (
    user_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    tree_access_mask BIGINT NOT NULL DEFAULT 0
);

ALTER TABLE "User"
ADD COLUMN IF NOT EXISTS tree_access_mask BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS "FamilyTree" (
    tree_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    surname VARCHAR(50) NOT NULL,
    revision_date DATE,
    creator_id INTEGER NOT NULL,
    CONSTRAINT fk_familytree_creator
        FOREIGN KEY (creator_id) REFERENCES "User"(user_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS "Person" (
    person_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tree_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    gender gender_type NOT NULL,
    birth_date DATE,
    generation INTEGER NOT NULL DEFAULT 1,
    death_date DATE,
    CONSTRAINT fk_person_tree
        FOREIGN KEY (tree_id) REFERENCES "FamilyTree"(tree_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

ALTER TABLE "Person"
ADD COLUMN IF NOT EXISTS generation INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS "Relationship" (
    person1_id INTEGER NOT NULL,
    person2_id INTEGER NOT NULL,
    rel_type rel_type_enum NOT NULL,
    PRIMARY KEY (person1_id, person2_id, rel_type),
    CONSTRAINT fk_relationship_person1
        FOREIGN KEY (person1_id) REFERENCES "Person"(person_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_relationship_person2
        FOREIGN KEY (person2_id) REFERENCES "Person"(person_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "FamilyTreeInvite" (
    invite_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tree_id INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    invitee_email VARCHAR(255) NOT NULL,
    invitee_user_id INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    invited_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    CONSTRAINT fk_invite_tree
        FOREIGN KEY (tree_id) REFERENCES "FamilyTree"(tree_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_invite_inviter
        FOREIGN KEY (inviter_id) REFERENCES "User"(user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_invite_user
        FOREIGN KEY (invitee_user_id) REFERENCES "User"(user_id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT ck_invite_status
        CHECK (status IN ('pending', 'accepted', 'revoked')),
    CONSTRAINT uq_tree_invitee UNIQUE (tree_id, invitee_email)
);

-- Physical optimization indexes
-- For ancestor / kinship recursive queries:
-- frequent predicate: rel_type='parent' AND person2_id = ?
-- and need to read person1_id (parent node).
CREATE INDEX IF NOT EXISTS idx_rel_parent_person2_person1
ON "Relationship" (person2_id, person1_id)
WHERE rel_type = 'parent';

CREATE INDEX IF NOT EXISTS idx_rel_parent_person1_person2
ON "Relationship" (person1_id, person2_id)
WHERE rel_type = 'parent';

-- For name prefix / fuzzy candidate search in Task 1:
-- the query filters visible trees and matches the first three characters of name.
CREATE INDEX IF NOT EXISTS idx_person_tree_name_prefix3
ON "Person" (
    tree_id,
    (SUBSTRING(name FROM 1 FOR 1)),
    (SUBSTRING(name FROM 2 FOR 1)),
    (SUBSTRING(name FROM 3 FOR 1)),
    person_id
);

-- Precomputed complete 2-generation ancestor view:
-- Store one row only when the person has 2 direct parents and each parent has 2 parents.
DROP MATERIALIZED VIEW IF EXISTS "Ancestor2";

CREATE MATERIALIZED VIEW "Ancestor2" AS
WITH direct_parent_edges AS (
    SELECT DISTINCT person2_id AS child_id, person1_id AS parent_id
    FROM "Relationship"
    WHERE rel_type = 'parent'
),
ranked_parents AS (
    SELECT
        child_id,
        parent_id,
        ROW_NUMBER() OVER (PARTITION BY child_id ORDER BY parent_id) AS rn,
        COUNT(*) OVER (PARTITION BY child_id) AS parent_cnt
    FROM direct_parent_edges
),
child_with_two_parents AS (
    SELECT
        child_id,
        MAX(parent_id) FILTER (WHERE rn = 1) AS parent1_id,
        MAX(parent_id) FILTER (WHERE rn = 2) AS parent2_id
    FROM ranked_parents
    WHERE parent_cnt = 2
    GROUP BY child_id
),
ranked_grandparents AS (
    SELECT
        child_id AS parent_id,
        parent_id AS grandparent_id,
        ROW_NUMBER() OVER (PARTITION BY child_id ORDER BY parent_id) AS rn,
        COUNT(*) OVER (PARTITION BY child_id) AS gp_cnt
    FROM direct_parent_edges
),
parent_with_two_grandparents AS (
    SELECT
        parent_id,
        MAX(grandparent_id) FILTER (WHERE rn = 1) AS grandparent1_id,
        MAX(grandparent_id) FILTER (WHERE rn = 2) AS grandparent2_id
    FROM ranked_grandparents
    WHERE gp_cnt = 2
    GROUP BY parent_id
)
SELECT
    c.child_id AS person_id,
    c.parent1_id,
    c.parent2_id,
    gp1.grandparent1_id AS grandparent1_id,
    gp1.grandparent2_id AS grandparent2_id,
    gp2.grandparent1_id AS grandparent3_id,
    gp2.grandparent2_id AS grandparent4_id
FROM child_with_two_parents c
JOIN parent_with_two_grandparents gp1 ON gp1.parent_id = c.parent1_id
JOIN parent_with_two_grandparents gp2 ON gp2.parent_id = c.parent2_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ancestor2_person
ON "Ancestor2" (person_id);

CREATE INDEX IF NOT EXISTS idx_ancestor2_parent1
ON "Ancestor2" (parent1_id);

CREATE INDEX IF NOT EXISTS idx_ancestor2_parent2
ON "Ancestor2" (parent2_id);

-- For generation-based analytics in Task 5:
-- frequent filters: tree_id + generation, and birth_date IS NOT NULL.
CREATE INDEX IF NOT EXISTS idx_person_tree_generation_birth_notnull
ON "Person" (tree_id, generation, birth_date)
WHERE birth_date IS NOT NULL;
