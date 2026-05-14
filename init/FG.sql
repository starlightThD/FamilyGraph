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
