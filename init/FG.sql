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

CREATE TABLE IF NOT EXISTS "User" (
    user_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE
);

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
    death_date DATE,
    CONSTRAINT fk_person_tree
        FOREIGN KEY (tree_id) REFERENCES "FamilyTree"(tree_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);

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

CREATE TABLE IF NOT EXISTS "KinshipClosure" (
    ancestor_id INTEGER NOT NULL,
    descendant_id INTEGER NOT NULL,
    depth INTEGER NOT NULL,
    PRIMARY KEY (ancestor_id, descendant_id),
    CONSTRAINT fk_closure_ancestor
        FOREIGN KEY (ancestor_id) REFERENCES "Person"(person_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_closure_descendant
        FOREIGN KEY (descendant_id) REFERENCES "Person"(person_id)
        ON UPDATE CASCADE ON DELETE CASCADE
);
