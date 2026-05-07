CREATE DATABASE IF NOT EXISTS FGDB
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE FGDB;

CREATE TABLE IF NOT EXISTS `User` (
        user_id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(255) UNIQUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS FamilyTree (
        tree_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        surname VARCHAR(50) NOT NULL,
        revision_date DATE,
        creator_id INT NOT NULL,
        CONSTRAINT fk_familytree_creator
            FOREIGN KEY (creator_id) REFERENCES `User`(user_id)
            ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS Person (
        person_id INT AUTO_INCREMENT PRIMARY KEY,
        tree_id INT NOT NULL,
        name VARCHAR(100) NOT NULL,
        gender ENUM('male','female','other') NOT NULL,
        birth_date DATE,
        death_date DATE,
        CONSTRAINT fk_person_tree
            FOREIGN KEY (tree_id) REFERENCES FamilyTree(tree_id)
            ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS Relationship (
        person1_id INT NOT NULL,
        person2_id INT NOT NULL,
        rel_type ENUM('parent','spouse') NOT NULL,
        PRIMARY KEY (person1_id, person2_id, rel_type),
        CONSTRAINT fk_relationship_person1
            FOREIGN KEY (person1_id) REFERENCES Person(person_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_relationship_person2
            FOREIGN KEY (person2_id) REFERENCES Person(person_id)
            ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS KinshipClosure (
        ancestor_id INT NOT NULL,
        descendant_id INT NOT NULL,
        depth INT NOT NULL,
        PRIMARY KEY (ancestor_id, descendant_id),
        CONSTRAINT fk_closure_ancestor
            FOREIGN KEY (ancestor_id) REFERENCES Person(person_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        CONSTRAINT fk_closure_descendant
            FOREIGN KEY (descendant_id) REFERENCES Person(person_id)
            ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB;