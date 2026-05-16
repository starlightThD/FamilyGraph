import os
import io
import csv
import zipfile
import time
from collections import defaultdict

import psycopg2
from flask import Flask, render_template, request, redirect, session, url_for, send_file, abort, jsonify, g
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

TABLES = [
	"User",
	"Person",
	"FamilyTree",
	"Relationship",
    "FamilyTreeInvite",
]

MAX_RELATIONSHIP_DEPTH = 50
try:
    RELATIONSHIP_SQL_TIMEOUT_MS = max(1, int(os.getenv("RELATIONSHIP_SQL_TIMEOUT_MS", "20000")))
except ValueError:
    RELATIONSHIP_SQL_TIMEOUT_MS = 20000
try:
    ACCESS_MASK_REFRESH_INTERVAL_SECONDS = max(
        1, int(os.getenv("ACCESS_MASK_REFRESH_INTERVAL_SECONDS", "60"))
    )
except ValueError:
    ACCESS_MASK_REFRESH_INTERVAL_SECONDS = 60


def extract_user_surname(username):
    """Treat the first character of username as the user's surname."""
    if not username:
        return None
    username = username.strip()
    return username[0] if username else None


def tree_bit(tree_id):
    if tree_id is None or tree_id < 1:
        return 0
    return 1 << (tree_id - 1)


def has_tree_access_mask(mask, tree_id):
    if not mask:
        return False
    return (int(mask) & tree_bit(tree_id)) != 0


def tree_ids_from_mask(mask):
    mask = int(mask or 0)
    bit = 1
    idx = 1
    ids = []
    while bit <= mask:
        if mask & bit:
            ids.append(idx)
        bit <<= 1
        idx += 1
    return ids


def get_current_user():
    if 'user_id' not in session:
        return None
    return {
        'user_id': session.get('user_id'),
        'username': session.get('username'),
        'email': session.get('email'),
        'is_admin': session.get('is_admin', False),
        'surname': session.get('surname'),
        'tree_access_mask': int(session.get('tree_access_mask', 0) or 0),
    }


def is_admin_view():
    user = get_current_user()
    return bool(user and user.get('is_admin'))


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fgdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


def is_safe_next_url(target):
    return bool(target and target.startswith('/') and not target.startswith('//'))


def apply_user_session(user_id, username, email, is_admin, access_mask):
    session.clear()
    session['user_id'] = user_id
    session['username'] = username
    session['email'] = email
    session['is_admin'] = is_admin
    session['surname'] = extract_user_surname(username)
    session['tree_access_mask'] = int(access_mask or 0)
    session['access_mask_refreshed_at'] = int(time.time())


def should_refresh_access_mask():
    last_refreshed_at = session.get('access_mask_refreshed_at')
    if last_refreshed_at is None:
        return True
    try:
        last_refreshed_at = int(last_refreshed_at)
    except (TypeError, ValueError):
        return True
    return (int(time.time()) - last_refreshed_at) >= ACCESS_MASK_REFRESH_INTERVAL_SECONDS


def rebuild_user_access_mask(cursor, user_id, username, email, is_admin):
    access_ids = set()
    if is_admin:
        cursor.execute('SELECT tree_id FROM "FamilyTree"')
        access_ids = {row[0] for row in cursor.fetchall()}
    else:
        surname = extract_user_surname(username)
        if surname:
            cursor.execute('SELECT tree_id FROM "FamilyTree" WHERE surname = %s', (surname,))
            access_ids.update(row[0] for row in cursor.fetchall())

        cursor.execute('SELECT tree_id FROM "FamilyTree" WHERE creator_id = %s', (user_id,))
        access_ids.update(row[0] for row in cursor.fetchall())

        if email:
            cursor.execute(
                """
                UPDATE "FamilyTreeInvite"
                SET invitee_user_id = %s,
                    status = 'accepted',
                    responded_at = CURRENT_TIMESTAMP
                WHERE invitee_email = %s
                  AND (invitee_user_id IS NULL OR invitee_user_id = %s)
                  AND status = 'pending'
                """,
                (user_id, email, user_id),
            )
            cursor.execute(
                """
                SELECT tree_id
                FROM "FamilyTreeInvite"
                WHERE status = 'accepted'
                  AND (invitee_user_id = %s OR invitee_email = %s)
                """,
                (user_id, email),
            )
            access_ids.update(row[0] for row in cursor.fetchall())

    access_mask = 0
    for tree_id in access_ids:
        access_mask |= tree_bit(tree_id)

    cursor.execute(
        """
        UPDATE "User"
        SET tree_access_mask = %s
        WHERE user_id = %s
        """,
        (access_mask, user_id),
    )
    return access_mask


def rebuild_user_access_mask_by_id(cursor, user_id):
    cursor.execute(
        """
        SELECT user_id, username, email, is_admin
        FROM "User"
        WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return 0
    return rebuild_user_access_mask(cursor, row[0], row[1], row[2], row[3])


def get_visible_tree_rows(cursor, user):
    if user is None:
        return []
    if user.get('is_admin'):
        cursor.execute(
            """
            SELECT f.tree_id, f.name, f.surname, u.username
            FROM "FamilyTree" f
            JOIN "User" u ON u.user_id = f.creator_id
            ORDER BY f.tree_id
            """
        )
        return cursor.fetchall()

    tree_ids = tree_ids_from_mask(user.get('tree_access_mask', 0))
    if not tree_ids:
        return []
    cursor.execute(
        """
        SELECT DISTINCT f.tree_id, f.name, f.surname, u.username
        FROM "FamilyTree" f
        JOIN "User" u ON u.user_id = f.creator_id
        WHERE f.tree_id = ANY(%s)
        ORDER BY f.tree_id
        """,
        (tree_ids,),
    )
    return cursor.fetchall()


def get_visible_tree_ids(cursor, user):
    return {row[0] for row in get_visible_tree_rows(cursor, user)}


def can_access_tree(cursor, user, tree_id):
    if user is None:
        return False
    cursor.execute('SELECT 1 FROM "FamilyTree" WHERE tree_id = %s', (tree_id,))
    if cursor.fetchone() is None:
        return False
    if user.get('is_admin'):
        return True
    return has_tree_access_mask(user.get('tree_access_mask', 0), tree_id)


def format_internal_node(person_id, name, generation, has_children=False, has_spouses=False):
    generation_display = generation if generation is not None else "?"
    return {
        "id": person_id,
        "name": name,
        "generation": generation,
        "label": f"{name} (ID {person_id}, G{generation_display})",
        "node_type": "internal",
        "has_children": bool(has_children),
        "has_spouses": bool(has_spouses),
        "spouses": [],
        "children": [],
    }


def format_spouse_node(person_id, name, generation):
    generation_display = generation if generation is not None else "?"
    return {
        "id": person_id,
        "name": name,
        "generation": generation,
        "label": f"{name} (ID {person_id}, G{generation_display})",
        "node_type": "spouse",
    }


def fetch_person_row_in_tree(cursor, tree_id, person_id):
    cursor.execute(
        """
        SELECT person_id, name, generation
        FROM "Person"
        WHERE tree_id = %s AND person_id = %s
        """,
        (tree_id, person_id),
    )
    return cursor.fetchone()


def fetch_default_root_row(cursor, tree_id):
    cursor.execute(
        """
        SELECT p.person_id, p.name, p.generation
        FROM "Person" p
        WHERE p.tree_id = %s
          AND NOT EXISTS (
              SELECT 1
              FROM "Relationship" r
              JOIN "Person" parent ON parent.person_id = r.person1_id
              WHERE r.rel_type = 'parent'
                AND r.person2_id = p.person_id
                AND parent.tree_id = %s
          )
        ORDER BY p.generation NULLS FIRST, p.person_id
        LIMIT 1
        """,
        (tree_id, tree_id),
    )
    root = cursor.fetchone()
    if root:
        return root

    cursor.execute(
        """
        SELECT person_id, name, generation
        FROM "Person"
        WHERE tree_id = %s
        ORDER BY person_id
        LIMIT 1
        """,
        (tree_id,),
    )
    return cursor.fetchone()


def fetch_has_children_ids(cursor, tree_id, person_ids):
    if not person_ids:
        return set()
    cursor.execute(
        """
        SELECT DISTINCT r.person1_id
        FROM "Relationship" r
        JOIN "Person" child ON child.person_id = r.person2_id
        WHERE r.rel_type = 'parent'
          AND r.person1_id = ANY(%s)
          AND child.tree_id = %s
        """,
        (person_ids, tree_id),
    )
    return {row[0] for row in cursor.fetchall()}


def fetch_has_spouse_ids(cursor, person_ids):
    if not person_ids:
        return set()
    cursor.execute(
        """
        SELECT DISTINCT node_id
        FROM (
            SELECT r.person1_id AS node_id
            FROM "Relationship" r
            WHERE r.rel_type = 'spouse' AND r.person1_id = ANY(%s)
            UNION
            SELECT r.person2_id AS node_id
            FROM "Relationship" r
            WHERE r.rel_type = 'spouse' AND r.person2_id = ANY(%s)
        ) spouse_nodes
        """,
        (person_ids, person_ids),
    )
    return {row[0] for row in cursor.fetchall()}


def build_descendant_tree(person_by_id, children_map, spouse_map, root_id):
    def build_node(person_id, path):
        person = person_by_id[person_id]
        label = f"{person['name']} (ID {person_id}, G{person.get('generation', '?')})"
        if person_id in path:
            return {
                "id": person_id,
                "name": person["name"],
                "generation": person.get("generation"),
                "label": f"{label} [cycle]",
                "node_type": "internal",
                "spouses": [],
                "children": [],
            }
        next_path = path | {person_id}
        return {
            "id": person_id,
            "name": person["name"],
            "generation": person.get("generation"),
            "label": label,
            "node_type": "internal",
            "spouses": spouse_map.get(person_id, []),
            "children": [build_node(cid, next_path) for cid in children_map.get(person_id, [])],
        }

    return build_node(root_id, set())


def build_ancestor_tree(cursor, person_id, max_depth=None):
    cursor.execute(
        """
        SELECT person_id, name, generation
        FROM "Person"
        WHERE person_id = %s
        """,
        (person_id,),
    )
    person_row = cursor.fetchone()
    if not person_row:
        return None

    depth_limit = max_depth if max_depth is not None else 100

    cursor.execute(
        """
        WITH RECURSIVE ancestor_edges AS (
            SELECT
                r.person2_id AS child_id,
                r.person1_id AS parent_id,
                1 AS depth,
                ARRAY[r.person2_id, r.person1_id] AS path
            FROM "Relationship" r
            WHERE r.rel_type = 'parent' AND r.person2_id = %s
            UNION ALL
            SELECT
                ae.parent_id AS child_id,
                r.person1_id AS parent_id,
                ae.depth + 1 AS depth,
                ae.path || r.person1_id
            FROM ancestor_edges ae
            JOIN "Relationship" r
              ON r.rel_type = 'parent'
             AND r.person2_id = ae.parent_id
            WHERE NOT (r.person1_id = ANY(ae.path))
              AND ae.depth < %s
        )
        SELECT
            ae.child_id,
            ae.parent_id,
            MIN(ae.depth) AS min_depth
        FROM ancestor_edges ae
        GROUP BY ae.child_id, ae.parent_id
        ORDER BY min_depth, ae.parent_id
        """,
        (person_id, depth_limit),
    )
    edge_rows = cursor.fetchall()
    if not edge_rows:
        return {"name": f"{person_row[1]} (ID {person_row[0]}, G{person_row[2]})", "children": []}

    ancestor_ids = {row[1] for row in edge_rows}
    cursor.execute(
        """
        SELECT person_id, name, generation
        FROM "Person"
        WHERE person_id = ANY(%s)
        """,
        (list(ancestor_ids),),
    )
    person_by_id = {person_row[0]: {"name": person_row[1], "generation": person_row[2]}}
    for pid, name, generation in cursor.fetchall():
        person_by_id[pid] = {"name": name, "generation": generation}

    parents_map = defaultdict(list)
    for child_id, parent_id, _depth in edge_rows:
        parents_map[child_id].append(parent_id)

    def build_node(node_id, path):
        person = person_by_id.get(node_id, {"name": "Unknown", "generation": "?"})
        label = f"{person['name']} (ID {node_id}, G{person.get('generation', '?')})"
        if node_id in path:
            return {"name": f"{label} [cycle]", "children": []}
        next_path = path | {node_id}
        return {
            "name": label,
            "children": [build_node(pid, next_path) for pid in parents_map.get(node_id, [])],
        }

    return build_node(person_row[0], set())


def format_ancestor_preview_node(person_id, name, generation, depth, has_parents, path_ids):
    generation_display = generation if generation is not None else "?"
    return {
        "id": person_id,
        "name": name,
        "generation": generation,
        "depth": depth,
        "label": f"{name} (ID {person_id}, G{generation_display})",
        "has_parents": bool(has_parents),
        "path_ids": path_ids,
    }


def format_descendant_preview_node(person_id, name, generation, gender, depth, has_children, path_ids):
    generation_display = generation if generation is not None else "?"
    return {
        "id": person_id,
        "name": name,
        "generation": generation,
        "gender": gender,
        "depth": depth,
        "label": f"{name} (ID {person_id}, G{generation_display})",
        "has_children": bool(has_children),
        "path_ids": path_ids,
    }


def parse_optional_max_depth(raw_value):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None, None
    try:
        max_depth = int(raw_value)
        if max_depth < 1:
            raise ValueError
    except ValueError:
        return None, "Max depth must be a positive number."
    return max_depth, None


def parse_path_ids(raw_path):
    raw_path = (raw_path or "").strip()
    if not raw_path:
        return None, "Path is required."
    tokens = [token.strip() for token in raw_path.split(",") if token.strip()]
    if not tokens:
        return None, "Path is required."
    try:
        path_ids = [int(token) for token in tokens]
    except ValueError:
        return None, "Path must contain numeric IDs only."
    if any(node_id < 1 for node_id in path_ids):
        return None, "Path IDs must be positive numbers."
    if len(set(path_ids)) != len(path_ids):
        return None, "Path cannot contain duplicate node IDs."
    return path_ids, None


def is_valid_ancestor_chain(cursor, path_ids):
    if len(path_ids) <= 1:
        return True
    for idx in range(1, len(path_ids)):
        child_id = path_ids[idx - 1]
        parent_id = path_ids[idx]
        cursor.execute(
            """
            SELECT 1
            FROM "Relationship"
            WHERE rel_type = 'parent'
              AND person1_id = %s
              AND person2_id = %s
            LIMIT 1
            """,
            (parent_id, child_id),
        )
        if cursor.fetchone() is None:
            return False
    return True


def is_valid_descendant_chain(cursor, path_ids):
    if len(path_ids) <= 1:
        return True
    for idx in range(1, len(path_ids)):
        parent_id = path_ids[idx - 1]
        child_id = path_ids[idx]
        cursor.execute(
            """
            SELECT 1
            FROM "Relationship"
            WHERE rel_type = 'parent'
              AND person1_id = %s
              AND person2_id = %s
            LIMIT 1
            """,
            (parent_id, child_id),
        )
        if cursor.fetchone() is None:
            return False
    return True


def query_task_1_kin_radius(person_id):
    """Input: person_id (int). Output: (message, person, parents, spouses, siblings, children, spouse_gate_note)."""
    # Purpose: fetch center person and depth-1 relations (parents, spouse, siblings, children).
    message = None
    spouse_gate_note = None
    person = None
    parents = []
    spouses = []
    siblings = []
    children = []

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT person_id, name, gender, tree_id, birth_date, death_date
                FROM "Person"
                WHERE person_id = %s
                """,
                (person_id,),
            )
            row = cursor.fetchone()
            if not row:
                message = f"Person ID {person_id} not found."
                return message, person, parents, spouses, siblings, children, spouse_gate_note

            person = {
                "id": row[0],
                "name": row[1],
                "gender": row[2],
                "tree_id": row[3],
                "birth_date": row[4],
                "death_date": row[5],
            }

            cursor.execute(
                """
                SELECT p.person_id, p.name
                FROM "Relationship" r
                JOIN "Person" p ON p.person_id = r.person1_id
                JOIN "FamilyTree" ft ON ft.tree_id = p.tree_id
                WHERE r.rel_type = 'parent' AND r.person2_id = %s
                ORDER BY
                  CASE WHEN ft.surname = (
                      SELECT ft0.surname
                      FROM "Person" p0
                      JOIN "FamilyTree" ft0 ON ft0.tree_id = p0.tree_id
                      WHERE p0.person_id = %s
                  ) THEN 0 ELSE 1 END,
                  p.person_id
                """,
                (person_id, person_id),
            )
            parents = cursor.fetchall()

            cursor.execute(
                """
                SELECT p.person_id, p.name
                FROM "Relationship" r
                JOIN "Person" p
                  ON (r.person1_id = %s AND p.person_id = r.person2_id)
                  OR (r.person2_id = %s AND p.person_id = r.person1_id)
                WHERE r.rel_type = 'spouse'
                  AND p.tree_id <> %s
                ORDER BY p.person_id
                """,
                (person_id, person_id, person["tree_id"]),
            )
            spouses = cursor.fetchall()

            cursor.execute(
                """
                SELECT p.person_id
                FROM "Relationship" r
                JOIN "Person" p ON p.person_id = r.person1_id
                WHERE r.rel_type = 'parent'
                  AND r.person2_id = %s
                  AND p.gender = 'male'
                ORDER BY p.person_id
                LIMIT 1
                """,
                (person_id,),
            )
            # father_row = cursor.fetchone()
            # if father_row:
            #     father_id = father_row[0]
            #     cursor.execute(
            #         """
            #         SELECT p.person_id, p.name
            #         FROM "Relationship" r
            #         JOIN "Person" p ON p.person_id = r.person2_id
            #         WHERE r.rel_type = 'parent'
            #           AND r.person1_id = %s
            #           AND p.person_id <> %s
            #         ORDER BY p.person_id
            #         """,
            #         (father_id, person_id),
            #     )
            #     siblings = cursor.fetchall()
            siblings = []

            if spouses:
                child_parent_id = person_id
                if person["gender"] == "female":
                    child_parent_id = spouses[0][0]

                cursor.execute(
                    """
                    SELECT p.person_id, p.name
                    FROM "Relationship" r
                    JOIN "Person" p ON p.person_id = r.person2_id
                    WHERE r.rel_type = 'parent' AND r.person1_id = %s
                    ORDER BY p.person_id
                    """,
                    (child_parent_id,),
                )
                children = cursor.fetchall()
            else:
                spouse_gate_note = "No spouse found; children lookup skipped."

    return message, person, parents, spouses, siblings, children, spouse_gate_note


def query_task_1_name_candidates(cursor, user, first_char, second_char, third_char, limit=120):
    """Input: 3 optional characters. Output: candidate members in visible trees."""
    visible_tree_ids = get_visible_tree_ids(cursor, user)
    if not visible_tree_ids:
        return []

    conditions = ['p.tree_id = ANY(%s)']
    params = [list(visible_tree_ids)]

    if first_char:
        conditions.append('SUBSTRING(p.name FROM 1 FOR 1) = %s')
        params.append(first_char)
    if second_char:
        conditions.append('SUBSTRING(p.name FROM 2 FOR 1) = %s')
        params.append(second_char)
    if third_char:
        conditions.append('SUBSTRING(p.name FROM 3 FOR 1) = %s')
        params.append(third_char)

    params.append(limit)
    query = f"""
        SELECT p.person_id, p.name, p.gender, p.tree_id, ft.name
        FROM "Person" p
        JOIN "FamilyTree" ft ON ft.tree_id = p.tree_id
        WHERE {' AND '.join(conditions)}
        ORDER BY p.tree_id, p.person_id
        LIMIT %s
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "gender": row[2],
            "tree_id": row[3],
            "tree_name": row[4],
        }
        for row in rows
    ]


def query_task_2_ancestors(person_id, max_depth):
    """Input: person_id (int), max_depth (int|None). Output: list of {id, name, depth}."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                WITH RECURSIVE ancestor_walk AS (
                    SELECT
                        seed.ancestor_id,
                        seed.step AS depth,
                        ARRAY[%s::INTEGER] || seed.append_path AS path
                    FROM (
                        SELECT
                            a2.grandparent1_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent1_id, a2.grandparent1_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = %s
                        UNION ALL
                        SELECT
                            a2.grandparent2_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent1_id, a2.grandparent2_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = %s
                        UNION ALL
                        SELECT
                            a2.grandparent3_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent2_id, a2.grandparent3_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = %s
                        UNION ALL
                        SELECT
                            a2.grandparent4_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent2_id, a2.grandparent4_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = %s
                        UNION ALL
                        SELECT
                            r.person1_id AS ancestor_id,
                            1 AS step,
                            ARRAY[r.person1_id] AS append_path
                        FROM "Relationship" r
                        WHERE r.rel_type = 'parent'
                          AND r.person2_id = %s
                          AND NOT EXISTS (
                              SELECT 1 FROM "Ancestor2" a2f WHERE a2f.person_id = %s
                          )
                    ) seed
                    WHERE (%s::INTEGER IS NULL OR seed.step <= %s::INTEGER)
                    UNION ALL
                    SELECT
                        nxt.ancestor_id,
                        aw.depth + nxt.step AS depth,
                        aw.path || nxt.append_path
                    FROM ancestor_walk aw
                    JOIN LATERAL (
                        SELECT
                            a2.grandparent1_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent1_id, a2.grandparent1_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = aw.ancestor_id
                        UNION ALL
                        SELECT
                            a2.grandparent2_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent1_id, a2.grandparent2_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = aw.ancestor_id
                        UNION ALL
                        SELECT
                            a2.grandparent3_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent2_id, a2.grandparent3_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = aw.ancestor_id
                        UNION ALL
                        SELECT
                            a2.grandparent4_id AS ancestor_id,
                            2 AS step,
                            ARRAY[a2.parent2_id, a2.grandparent4_id] AS append_path
                        FROM "Ancestor2" a2
                        WHERE a2.person_id = aw.ancestor_id
                        UNION ALL
                        SELECT
                            r.person1_id AS ancestor_id,
                            1 AS step,
                            ARRAY[r.person1_id] AS append_path
                        FROM "Relationship" r
                        WHERE r.rel_type = 'parent'
                          AND r.person2_id = aw.ancestor_id
                          AND NOT EXISTS (
                              SELECT 1 FROM "Ancestor2" a2f WHERE a2f.person_id = aw.ancestor_id
                          )
                    ) nxt ON TRUE
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM unnest(nxt.append_path) AS step_id(id)
                        WHERE step_id.id = ANY(aw.path)
                    )
                      AND (%s::INTEGER IS NULL OR aw.depth + nxt.step <= %s::INTEGER)
                )
                , ancestor_nodes AS (
                    SELECT
                        node.person_id AS ancestor_id,
                        node.ord - 1 AS depth
                    FROM ancestor_walk aw
                    CROSS JOIN LATERAL unnest(aw.path) WITH ORDINALITY AS node(person_id, ord)
                    WHERE node.ord > 1
                )
                SELECT
                    an.ancestor_id,
                    p.name,
                    MIN(an.depth) AS depth
                FROM ancestor_nodes an
                JOIN "Person" p ON p.person_id = an.ancestor_id
                GROUP BY an.ancestor_id, p.name
                HAVING (%s::INTEGER IS NULL OR MIN(an.depth) <= %s::INTEGER)
                ORDER BY MIN(an.depth), an.ancestor_id
            """
            cursor.execute(
                query,
                (
                    person_id,
                    person_id,
                    person_id,
                    person_id,
                    person_id,
                    person_id,
                    person_id,
                    max_depth,
                    max_depth,
                    max_depth,
                    max_depth,
                    max_depth,
                    max_depth,
                ),
            )
            rows = cursor.fetchall()

    return [{"id": r[0], "name": r[1], "depth": r[2]} for r in rows]


def query_task_6_descendants(person_id, max_depth, visible_tree_ids):
    """Input: person_id (int), max_depth (int|None). Output: list of direct descendants."""
    if not visible_tree_ids:
        return []
    with get_connection() as conn:
        with conn.cursor() as cursor:
            query = """
                WITH RECURSIVE descendant_walk AS (
                    SELECT
                        c.person_id AS descendant_id,
                        1 AS depth,
                        ARRAY[%s::INTEGER, c.person_id] AS path
                    FROM "Relationship" r
                    JOIN "Person" c ON c.person_id = r.person2_id
                    WHERE r.rel_type = 'parent'
                      AND r.person1_id = %s
                      AND c.tree_id = ANY(%s)
                    UNION ALL
                    SELECT
                        c.person_id AS descendant_id,
                        dw.depth + 1 AS depth,
                        dw.path || c.person_id
                    FROM descendant_walk dw
                    JOIN "Relationship" r
                      ON r.rel_type = 'parent'
                     AND r.person1_id = dw.descendant_id
                    JOIN "Person" c ON c.person_id = r.person2_id
                    WHERE c.tree_id = ANY(%s)
                      AND NOT (c.person_id = ANY(dw.path))
                )
                SELECT
                    dw.descendant_id,
                    p.name,
                    p.gender,
                    MIN(dw.depth) AS depth
                FROM descendant_walk dw
                JOIN "Person" p ON p.person_id = dw.descendant_id
                GROUP BY dw.descendant_id, p.name, p.gender
                HAVING (%s::INTEGER IS NULL OR MIN(dw.depth) <= %s::INTEGER)
                ORDER BY MIN(dw.depth), dw.descendant_id
            """
            cursor.execute(
                query,
                (person_id, person_id, list(visible_tree_ids), list(visible_tree_ids), max_depth, max_depth),
            )
            rows = cursor.fetchall()

    return [{"id": r[0], "name": r[1], "gender": r[2], "depth": r[3]} for r in rows]


def query_relationship_path(from_id, to_id, max_depth=MAX_RELATIONSHIP_DEPTH, timeout_ms=None):
    """Input: from_id (int), to_id (int). Output: dict with path info or None."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if timeout_ms is not None:
                timeout_ms = max(1, int(timeout_ms))
                cursor.execute("SET LOCAL statement_timeout = %s", (f"{timeout_ms}ms",))
            cursor.execute(
                """
                WITH RECURSIVE from_walk AS (
                    SELECT
                        %s::INTEGER AS start_id,
                        %s::INTEGER AS current_id,
                        ARRAY[%s::INTEGER] AS path,
                        0 AS depth
                    UNION ALL
                    SELECT
                        fw.start_id,
                        r.person1_id AS current_id,
                        fw.path || r.person1_id,
                        fw.depth + 1
                    FROM from_walk fw
                    JOIN "Relationship" r
                      ON r.rel_type = 'parent'
                     AND r.person2_id = fw.current_id
                    WHERE NOT (r.person1_id = ANY(fw.path))
                      AND fw.depth < %s
                ),
                to_walk AS (
                    SELECT
                        %s::INTEGER AS start_id,
                        %s::INTEGER AS current_id,
                        ARRAY[%s::INTEGER] AS path,
                        0 AS depth
                    UNION ALL
                    SELECT
                        tw.start_id,
                        r.person1_id AS current_id,
                        tw.path || r.person1_id,
                        tw.depth + 1
                    FROM to_walk tw
                    JOIN "Relationship" r
                      ON r.rel_type = 'parent'
                     AND r.person2_id = tw.current_id
                    WHERE NOT (r.person1_id = ANY(tw.path))
                      AND tw.depth < %s
                )
                SELECT f.path AS path_from,
                       t.path AS path_to,
                       (f.depth + t.depth) AS total_depth
                FROM from_walk f
                JOIN to_walk t
                  ON t.current_id = f.current_id
                ORDER BY total_depth
                LIMIT 1
                """,
                (from_id, from_id, from_id, max_depth, to_id, to_id, to_id, max_depth),
            )
            row = cursor.fetchone()
            if not row:
                return None
            path_from = row[0]
            path_to = row[1]
            depth = row[2]

            path_ids = path_from + list(reversed(path_to[:-1]))

            cursor.execute(
                """
                SELECT person_id, name
                FROM "Person"
                WHERE person_id = ANY(%s)
                """,
                (path_ids,),
            )
            name_by_id = {pid: name for pid, name in cursor.fetchall()}

    path = [{"id": pid, "name": name_by_id.get(pid, "Unknown")} for pid in path_ids]
    path_text = " -> ".join(f"{node['name']}({node['id']})" for node in path)
    return {"path": path, "path_text": path_text, "depth": depth}


def query_relationship_path_python(from_id, to_id, max_depth=MAX_RELATIONSHIP_DEPTH):
    """Input: from_id (int), to_id (int). Output: dict with path info or None."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            def build_paths(start_id):
                paths = {start_id: [start_id]}
                frontier = [start_id]
                depth = 0
                while frontier and depth < max_depth:
                    cursor.execute(
                        """
                        SELECT person2_id, person1_id
                        FROM "Relationship"
                        WHERE rel_type = 'parent'
                          AND person2_id = ANY(%s)
                        """,
                        (frontier,),
                    )
                    rows = cursor.fetchall()
                    next_frontier = []
                    for child_id, parent_id in rows:
                        child_path = paths.get(child_id)
                        if not child_path:
                            continue
                        if parent_id in paths or parent_id in child_path:
                            continue
                        paths[parent_id] = child_path + [parent_id]
                        next_frontier.append(parent_id)
                    if not next_frontier:
                        break
                    frontier = list(dict.fromkeys(next_frontier))
                    depth += 1
                return paths

            from_paths = build_paths(from_id)
            to_paths = build_paths(to_id)
            common = set(from_paths).intersection(to_paths)
            if not common:
                return None

            def score(node_id):
                return (len(from_paths[node_id]) + len(to_paths[node_id]) - 2)

            lca = min(common, key=score)
            path_ids = from_paths[lca] + list(reversed(to_paths[lca][:-1]))
            depth = len(path_ids) - 1

            cursor.execute(
                """
                SELECT person_id, name
                FROM "Person"
                WHERE person_id = ANY(%s)
                """,
                (path_ids,),
            )
            name_by_id = {pid: name for pid, name in cursor.fetchall()}

    path = [{"id": pid, "name": name_by_id.get(pid, "Unknown")} for pid in path_ids]
    path_text = " -> ".join(f"{node['name']}({node['id']})" for node in path)
    return {"path": path, "path_text": path_text, "depth": depth}


def query_task_3_longest_lived_generation(tree_id):
    """Input: tree_id (int). Output: (summary dict, generation_stats list)."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE roots AS (
                    SELECT p.person_id
                    FROM "Person" p
                    WHERE p.tree_id = %s
                      AND NOT EXISTS (
                          SELECT 1
                          FROM "Relationship" r
                          WHERE r.rel_type = 'parent'
                            AND r.person2_id = p.person_id
                      )
                ),
                tree_walk AS (
                    SELECT
                        rt.person_id AS person_id,
                        0 AS depth
                    FROM roots rt
                    UNION
                    SELECT
                        r.person2_id AS person_id,
                        tw.depth + 1 AS depth
                    FROM tree_walk tw
                    JOIN "Relationship" r
                      ON r.rel_type = 'parent'
                     AND r.person1_id = tw.person_id
                    WHERE tw.depth < 120
                ),
                gen_depths AS (
                    SELECT tw.person_id, MIN(tw.depth) AS depth
                    FROM tree_walk tw
                    GROUP BY tw.person_id
                )
                SELECT
                    gd.depth,
                    AVG(EXTRACT(YEAR FROM age(COALESCE(p.death_date, CURRENT_DATE), p.birth_date))) AS avg_lifespan,
                    COUNT(*) AS member_count
                FROM gen_depths gd
                JOIN "Person" p ON p.person_id = gd.person_id
                WHERE p.tree_id = %s AND p.birth_date IS NOT NULL
                GROUP BY gd.depth
                ORDER BY gd.depth
                """,
                (tree_id, tree_id),
            )
            rows = cursor.fetchall()

    generation_stats = [
        {"depth": r[0], "avg_lifespan": r[1], "member_count": r[2]}
        for r in rows
    ]
    valid_stats = [row for row in generation_stats if row["avg_lifespan"] is not None]
    if valid_stats:
        best_gen = max(valid_stats, key=lambda x: x["avg_lifespan"])
        summary = {
            "best_depth": best_gen["depth"],
            "avg_lifespan": best_gen["avg_lifespan"],
            "member_count": best_gen["member_count"],
        }
    else:
        summary = {
            "best_depth": None,
            "avg_lifespan": None,
            "member_count": 0,
        }

    return summary, generation_stats

def query_task_4_filter_members(filters):
    """Input: filters dict. Output: list of member dicts that match filters."""
    tree_id = filters.get("tree_id")
    min_age = filters.get("min_age")
    max_age = filters.get("max_age")
    married = filters.get("married", "any")
    has_children = filters.get("has_children", "any")
    alive = filters.get("alive", "any")
    gender = filters.get("gender", "any")

    age_expr = "EXTRACT(YEAR FROM age(COALESCE(p.death_date, CURRENT_DATE), p.birth_date))"
    query = [
        "SELECT p.person_id, p.name,",
        f"       {age_expr} AS age_years,",
        "       (p.death_date IS NULL) AS is_alive",
        "FROM \"Person\" p",
        "WHERE p.tree_id = %s",
    ]
    params = [tree_id]

    if min_age is not None or max_age is not None:
        query.append("AND p.birth_date IS NOT NULL")
    if min_age is not None:
        query.append(f"AND {age_expr} >= %s")
        params.append(min_age)
    if max_age is not None:
        query.append(f"AND {age_expr} <= %s")
        params.append(max_age)
    if gender in {"male", "female", "other"}:
        query.append("AND p.gender = %s")
        params.append(gender)

    if married == "yes":
        query.append(
            "AND EXISTS (SELECT 1 FROM \"Relationship\" r "
            "WHERE r.rel_type = 'spouse' "
            "AND (r.person1_id = p.person_id OR r.person2_id = p.person_id))"
        )
        if has_children == "yes":
            query.append(
                "AND EXISTS (SELECT 1 FROM \"Relationship\" r "
                "WHERE r.rel_type = 'parent' AND r.person1_id = p.person_id)"
            )
        elif has_children == "no":
            query.append(
                "AND NOT EXISTS (SELECT 1 FROM \"Relationship\" r "
                "WHERE r.rel_type = 'parent' AND r.person1_id = p.person_id)"
            )
    elif married == "no":
        query.append(
            "AND NOT EXISTS (SELECT 1 FROM \"Relationship\" r "
            "WHERE r.rel_type = 'spouse' "
            "AND (r.person1_id = p.person_id OR r.person2_id = p.person_id))"
        )
        query.append(
            "AND NOT EXISTS (SELECT 1 FROM \"Relationship\" r "
            "WHERE r.rel_type = 'parent' AND r.person1_id = p.person_id)"
        )

    if alive == "yes":
        query.append("AND p.death_date IS NULL")
    elif alive == "no":
        query.append("AND p.death_date IS NOT NULL")
    
    query.append("ORDER BY p.person_id")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("\n".join(query), params)
            rows = cursor.fetchall()

    return [
        {"id": r[0], "name": r[1], "age": r[2], "alive": r[3]}
        for r in rows
    ]


def query_task_5_early_births(tree_id, generation_depth):
    """Input: tree_id (int), generation_depth (int|None). Output: list of matching members."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                WITH
                gen_avg AS (
                    SELECT
                        p.generation,
                        AVG(EXTRACT(YEAR FROM p.birth_date)) AS avg_birth_year
                    FROM "Person" p
                    WHERE p.tree_id = %s
                      AND p.birth_date IS NOT NULL
                    GROUP BY p.generation
                )
                SELECT
                    p.person_id,
                    p.name,
                    EXTRACT(YEAR FROM p.birth_date) AS birth_year,
                    ga.avg_birth_year,
                    p.generation
                FROM "Person" p
                JOIN gen_avg ga ON ga.generation = p.generation
                WHERE p.tree_id = %s
                  AND p.birth_date IS NOT NULL
                  AND EXTRACT(YEAR FROM p.birth_date) < ga.avg_birth_year
                  AND (%s IS NULL OR p.generation = %s)
                ORDER BY p.generation, birth_year, p.person_id
                """,
                (tree_id, tree_id, generation_depth, generation_depth),
            )
            rows = cursor.fetchall()

    return [
        {
            "id": r[0],
            "name": r[1],
            "birth_year": r[2],
            "avg_birth_year": r[3],
            "generation_depth": r[4],
        }
        for r in rows
    ]


@app.context_processor
def inject_access_context():
    user = get_current_user()
    if not user:
        viewer_role = 'guest'
    elif user.get('is_admin'):
        viewer_role = 'admin'
    else:
        viewer_role = 'member'
    return {
        'viewer_role': viewer_role,
        'can_edit': bool(user),
        'current_user': user,
    }


@app.before_request
def begin_request_timing():
    g.request_started_at = time.perf_counter()


@app.after_request
def append_request_timing_headers(response):
    started_at = getattr(g, "request_started_at", None)
    if started_at is None:
        return response

    duration_ms = (time.perf_counter() - started_at) * 1000
    response.headers["X-Server-Time-Ms"] = f"{duration_ms:.2f}"

    timing_metric = f'app;desc="backend";dur={duration_ms:.2f}'
    existing_timing = response.headers.get("Server-Timing")
    if existing_timing:
        response.headers["Server-Timing"] = f"{existing_timing}, {timing_metric}"
    else:
        response.headers["Server-Timing"] = timing_metric

    return response


@app.before_request
def require_login():
    public_endpoints = {"login", "register", "static"}
    endpoint = request.endpoint
    if endpoint in public_endpoints:
        return None
    user = get_current_user()
    if user is None:
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for('login', next=next_url))
    if should_refresh_access_mask():
        with get_connection() as conn:
            with conn.cursor() as cursor:
                refreshed_access_mask = rebuild_user_access_mask(
                    cursor,
                    user['user_id'],
                    user['username'],
                    user['email'],
                    user['is_admin'],
                )
                conn.commit()
        apply_user_session(
            user['user_id'],
            user['username'],
            user['email'],
            user['is_admin'],
            refreshed_access_mask,
        )
    return None


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    message = None
    if request.method == 'POST':
        identity = request.form.get('username', '').strip()
        if not identity:
            message = "Please enter your username/email."
        else:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT user_id, username, email, password_hash, is_admin, tree_access_mask
                        FROM "User"
                        WHERE username = %s OR email = %s
                        LIMIT 1
                        """,
                        (identity, identity),
                    )
                    row = cursor.fetchone()
            if not row:
                message = "Invalid username/email."
            else:
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        access_mask = rebuild_user_access_mask(
                            cursor,
                            row[0],
                            row[1],
                            row[2],
                            row[4],
                        )
                        conn.commit()
                apply_user_session(row[0], row[1], row[2], row[4], access_mask)
                next_url = request.args.get('next', '').strip()
                if is_safe_next_url(next_url):
                    return redirect(next_url)
                return redirect(url_for('dashboard'))
    return render_template('login.html', message=message)


@app.route('/register', methods=['GET', 'POST'])
def register():
    message = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        if not username or not email:
            message = "Please complete all required fields."
        else:
            password_hash = generate_password_hash(password or "dev-register-no-password")
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM \"User\" WHERE username = %s OR email = %s",
                        (username, email),
                    )
                    exists = cursor.fetchone()
                    if exists:
                        message = "Username or email already exists."
                    else:
                        cursor.execute(
                            """
                            INSERT INTO "User" (username, password_hash, email, is_admin)
                            VALUES (%s, %s, %s, FALSE)
                            RETURNING user_id, username, email, is_admin, tree_access_mask
                            """,
                            (username, password_hash, email),
                        )
                        row = cursor.fetchone()
                        access_mask = rebuild_user_access_mask(
                            cursor,
                            row[0],
                            row[1],
                            row[2],
                            row[3],
                        )
                        conn.commit()
                        apply_user_session(row[0], row[1], row[2], row[3], access_mask)
                        return redirect(url_for('dashboard'))
    return render_template('register.html', message=message)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/dashboard')
def dashboard():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM \"Person\"')
            total_members = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM \"Person\" WHERE gender = \'male\'")
            male_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM \"Person\" WHERE gender = \'female\'")
            female_count = cursor.fetchone()[0]
    stats = {"total_members": total_members, "male_count": male_count, "female_count": female_count}
    return render_template('dashboard.html', stats=stats)


@app.route('/family-trees', methods=['GET', 'POST'])
def family_trees():
    message = None
    current_user = get_current_user()
    scope_text = "All trees"
    access_mask_text = "0"
    accessible_tree_names = []
    member_results = []
    invite_rows = []
    edit_tree = None
    refresh_current_session = False
    refreshed_access_mask = current_user.get('tree_access_mask', 0) if current_user else 0
    need_refresh_ancestor2 = False

    if request.method == 'POST':
        action = request.form.get('action', '').strip()
        if not current_user:
            message = "Please log in first."
        else:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    if action == "save_tree":
                        tree_id_raw = request.form.get('tree_id', '').strip()
                        tree_name = request.form.get('tree_name', '').strip()
                        surname = request.form.get('surname', '').strip() or "Unspecified"
                        creator_id = current_user['user_id']
                        if not tree_name:
                            message = "Tree name cannot be empty."
                        else:
                            if tree_id_raw:
                                try:
                                    tree_id = int(tree_id_raw)
                                except ValueError:
                                    message = "Tree ID must be a number."
                                else:
                                    if not can_access_tree(cursor, current_user, tree_id):
                                        message = "You do not have permission to update this family tree."
                                    else:
                                        cursor.execute(
                                            """
                                            UPDATE "FamilyTree"
                                            SET name = %s, surname = %s, revision_date = CURRENT_DATE
                                            WHERE tree_id = %s
                                            """,
                                            (tree_name, surname, tree_id),
                                        )
                                        if cursor.rowcount == 0:
                                            message = f"Family tree {tree_id} not found."
                                        else:
                                            message = f"Family tree {tree_id} updated."
                            else:
                                cursor.execute(
                                    """
                                    INSERT INTO "FamilyTree" (name, surname, revision_date, creator_id)
                                    VALUES (%s, %s, CURRENT_DATE, %s)
                                    RETURNING tree_id
                                    """,
                                    (tree_name, surname, creator_id),
                                )
                                created_tree_id = cursor.fetchone()[0]
                                refreshed_access_mask = rebuild_user_access_mask_by_id(cursor, creator_id)
                                refresh_current_session = True
                                message = f"Family tree {created_tree_id} created."

                    elif action == "delete_tree":
                        tree_id_raw = request.form.get('tree_id', '').strip()
                        try:
                            tree_id = int(tree_id_raw)
                        except ValueError:
                            message = "Tree ID must be a number."
                        else:
                            if not can_access_tree(cursor, current_user, tree_id):
                                message = "You do not have permission to delete this family tree."
                            else:
                                cursor.execute('DELETE FROM "FamilyTree" WHERE tree_id = %s', (tree_id,))
                                if cursor.rowcount == 0:
                                    message = f"Family tree {tree_id} not found."
                                else:
                                    refreshed_access_mask = rebuild_user_access_mask_by_id(cursor, current_user['user_id'])
                                    refresh_current_session = True
                                    message = f"Family tree {tree_id} deleted."

                    elif action == "invite_collaborator":
                        tree_id_raw = request.form.get('tree_id', '').strip()
                        invitee_email = request.form.get('invitee_email', '').strip().lower()
                        try:
                            tree_id = int(tree_id_raw)
                        except ValueError:
                            message = "Tree ID must be a number."
                            tree_id = None

                        if message is None:
                            if not invitee_email:
                                message = "Invitee email cannot be empty."
                            else:
                                if not can_access_tree(cursor, current_user, tree_id):
                                    message = "You do not have permission to invite collaborators to this tree."
                                else:
                                    cursor.execute(
                                        'SELECT user_id FROM "User" WHERE email = %s LIMIT 1',
                                        (invitee_email,),
                                    )
                                    user_row = cursor.fetchone()
                                    invitee_user_id = user_row[0] if user_row else None
                                    status = 'accepted' if invitee_user_id else 'pending'
                                    cursor.execute(
                                        """
                                        INSERT INTO "FamilyTreeInvite"
                                            (tree_id, inviter_id, invitee_email, invitee_user_id, status, responded_at)
                                        VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'accepted' THEN CURRENT_TIMESTAMP ELSE NULL END)
                                        ON CONFLICT (tree_id, invitee_email)
                                        DO UPDATE SET
                                            inviter_id = EXCLUDED.inviter_id,
                                            invitee_user_id = EXCLUDED.invitee_user_id,
                                            status = EXCLUDED.status,
                                            responded_at = CASE
                                                WHEN EXCLUDED.status = 'accepted' THEN CURRENT_TIMESTAMP
                                                ELSE "FamilyTreeInvite".responded_at
                                            END
                                        """,
                                        (
                                            tree_id,
                                            current_user['user_id'],
                                            invitee_email,
                                            invitee_user_id,
                                            status,
                                            status,
                                        ),
                                    )
                                    if status == 'accepted':
                                        if invitee_user_id:
                                            rebuild_user_access_mask_by_id(cursor, invitee_user_id)
                                        message = f"Invitation accepted immediately for {invitee_email}."
                                    else:
                                        message = f"Invitation sent to {invitee_email}."

                    elif action == "create_member":
                        tree_id_raw = request.form.get('member_tree_id', '').strip()
                        name = request.form.get('member_name', '').strip()
                        gender = request.form.get('gender', '').strip()
                        birth_date = request.form.get('birth_date', '').strip() or None
                        generation_raw = request.form.get('generation', '').strip()
                        death_date = request.form.get('death_date', '').strip() or None
                        father_id_raw = request.form.get('father_id', '').strip()
                        mother_id_raw = request.form.get('mother_id', '').strip()
                        spouse_id_raw = request.form.get('spouse_id', '').strip()

                        if not name or gender not in {'male', 'female', 'other'}:
                            message = "Member name and valid gender are required."
                        else:
                            try:
                                tree_id = int(tree_id_raw)
                            except ValueError:
                                message = "Member tree ID must be a number."
                            else:
                                if not can_access_tree(cursor, current_user, tree_id):
                                    message = "You do not have permission to modify members in this tree."
                        if message is None:
                            try:
                                generation = int(generation_raw)
                                if generation < 1:
                                    raise ValueError
                            except ValueError:
                                message = "Generation must be a positive number."

                        if message is None:
                            cursor.execute(
                                """
                                INSERT INTO "Person" (tree_id, name, gender, birth_date, generation, death_date)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                RETURNING person_id
                                """,
                                (tree_id, name, gender, birth_date, generation, death_date),
                            )
                            new_member_id = cursor.fetchone()[0]

                            for raw_parent_id in (father_id_raw, mother_id_raw):
                                if not raw_parent_id:
                                    continue
                                try:
                                    parent_id = int(raw_parent_id)
                                except ValueError:
                                    continue
                                cursor.execute(
                                    'SELECT 1 FROM "Person" WHERE person_id = %s AND tree_id = %s',
                                    (parent_id, tree_id),
                                )
                                if cursor.fetchone():
                                    cursor.execute(
                                        """
                                        INSERT INTO "Relationship" (person1_id, person2_id, rel_type)
                                        VALUES (%s, %s, 'parent')
                                        ON CONFLICT DO NOTHING
                                        """,
                                        (parent_id, new_member_id),
                                    )
                                    if cursor.rowcount > 0:
                                        need_refresh_ancestor2 = True

                            if spouse_id_raw:
                                try:
                                    spouse_id = int(spouse_id_raw)
                                except ValueError:
                                    spouse_id = None
                                if spouse_id is not None:
                                    cursor.execute(
                                        'SELECT 1 FROM "Person" WHERE person_id = %s AND tree_id = %s',
                                        (spouse_id, tree_id),
                                    )
                                    if cursor.fetchone() and spouse_id != new_member_id:
                                        a, b = sorted((spouse_id, new_member_id))
                                        cursor.execute(
                                            """
                                            INSERT INTO "Relationship" (person1_id, person2_id, rel_type)
                                            VALUES (%s, %s, 'spouse')
                                            ON CONFLICT DO NOTHING
                                            """,
                                            (a, b),
                                        )

                            message = f"Member {name} created (ID {new_member_id})."

                    elif action == "update_member":
                        member_id_raw = request.form.get('edit_member_id', '').strip()
                        name = request.form.get('edit_member_name', '').strip()
                        gender = request.form.get('edit_gender', '').strip()
                        birth_date = request.form.get('edit_birth_date', '').strip() or None
                        generation_raw = request.form.get('edit_generation', '').strip()
                        death_date = request.form.get('edit_death_date', '').strip() or None
                        try:
                            member_id = int(member_id_raw)
                        except ValueError:
                            message = "Member ID must be a number."
                        else:
                            if not name or gender not in {'male', 'female', 'other'}:
                                message = "Edit member requires name and valid gender."
                            else:
                                try:
                                    generation = int(generation_raw)
                                    if generation < 1:
                                        raise ValueError
                                except ValueError:
                                    message = "Generation must be a positive number."
                            if message is None:
                                cursor.execute(
                                    'SELECT tree_id FROM "Person" WHERE person_id = %s',
                                    (member_id,),
                                )
                                row = cursor.fetchone()
                                if not row:
                                    message = f"Member {member_id} not found."
                                elif not can_access_tree(cursor, current_user, row[0]):
                                    message = "You do not have permission to update this member."
                                else:
                                    cursor.execute(
                                        """
                                        UPDATE "Person"
                                        SET name = %s, gender = %s, birth_date = %s, generation = %s, death_date = %s
                                        WHERE person_id = %s
                                        """,
                                        (name, gender, birth_date, generation, death_date, member_id),
                                    )
                                    if cursor.rowcount == 0:
                                        message = f"Member {member_id} not found."
                                    else:
                                        message = f"Member {member_id} updated."

                    elif action == "delete_member":
                        member_id_raw = request.form.get('delete_member_id', '').strip()
                        try:
                            member_id = int(member_id_raw)
                        except ValueError:
                            message = "Member ID must be a number."
                        else:
                            cursor.execute(
                                'SELECT tree_id FROM "Person" WHERE person_id = %s',
                                (member_id,),
                            )
                            row = cursor.fetchone()
                            if not row:
                                message = f"Member {member_id} not found."
                            elif not can_access_tree(cursor, current_user, row[0]):
                                message = "You do not have permission to delete this member."
                            else:
                                cursor.execute('DELETE FROM "Person" WHERE person_id = %s', (member_id,))
                                if cursor.rowcount == 0:
                                    message = f"Member {member_id} not found."
                                else:
                                    need_refresh_ancestor2 = True
                                    message = f"Member {member_id} deleted."

                conn.commit()
                if need_refresh_ancestor2:
                    cursor.execute('REFRESH MATERIALIZED VIEW "Ancestor2"')
                    conn.commit()
                if refresh_current_session and current_user:
                    cursor.execute(
                        'SELECT user_id, username, email, is_admin FROM "User" WHERE user_id = %s',
                        (current_user['user_id'],),
                    )
                    user_row = cursor.fetchone()
                    if user_row:
                        apply_user_session(
                            user_row[0],
                            user_row[1],
                            user_row[2],
                            user_row[3],
                            refreshed_access_mask,
                        )
                        current_user = get_current_user()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            rows = get_visible_tree_rows(cursor, current_user)
            visible_tree_ids = {row[0] for row in rows}
            if current_user and current_user.get('is_admin'):
                scope_text = "Admin view: all trees"
            else:
                accessible_tree_names = [r[1] for r in rows]
                access_mask_text = str(current_user.get('tree_access_mask', 0))
                scope_text = (
                    f"Mask access (surname+invites), mask={access_mask_text}, "
                    f"trees={', '.join(accessible_tree_names) if accessible_tree_names else 'none'}"
                )

            edit_tree_id_raw = request.args.get('edit_tree_id', '').strip()
            if edit_tree_id_raw:
                try:
                    edit_tree_id = int(edit_tree_id_raw)
                except ValueError:
                    message = message or "Edit tree ID must be a number."
                else:
                    if edit_tree_id in visible_tree_ids:
                        cursor.execute(
                            """
                            SELECT tree_id, name, surname
                            FROM "FamilyTree"
                            WHERE tree_id = %s
                            """,
                            (edit_tree_id,),
                        )
                        row = cursor.fetchone()
                        if row:
                            edit_tree = {"id": row[0], "name": row[1], "surname": row[2]}

            keyword = request.args.get('keyword', '').strip()
            search_tree_id_raw = request.args.get('search_tree_id', '').strip()
            search_tree_id = None
            if search_tree_id_raw:
                try:
                    search_tree_id = int(search_tree_id_raw)
                except ValueError:
                    message = message or "Search tree ID must be a number."

            if keyword:
                tree_filter = search_tree_id if search_tree_id in visible_tree_ids else None
                tree_ids_for_query = list(visible_tree_ids)
                if tree_ids_for_query:
                    query = """
                        SELECT
                            p.person_id, p.name, p.gender, p.birth_date, p.generation, p.death_date,
                            p.tree_id, ft.name
                        FROM "Person" p
                        JOIN "FamilyTree" ft ON ft.tree_id = p.tree_id
                        WHERE p.tree_id = ANY(%s)
                          AND p.name ILIKE %s
                    """
                    params = [tree_ids_for_query, f"%{keyword}%"]
                    if tree_filter is not None:
                        query += " AND p.tree_id = %s"
                        params.append(tree_filter)
                    query += " ORDER BY p.tree_id, p.person_id LIMIT 200"
                    cursor.execute(query, params)
                    member_results = cursor.fetchall()

            if is_admin_view():
                cursor.execute(
                    """
                    SELECT i.invite_id, i.tree_id, i.invitee_email, i.status, i.invited_at, i.responded_at
                    FROM "FamilyTreeInvite" i
                    ORDER BY i.invited_at DESC
                    LIMIT 30
                    """
                )
                invite_rows = cursor.fetchall()

    trees = [
        {
            "id": r[0],
            "name": r[1],
            "surname": r[2],
            "role": f"Creator: {r[3]} (Surname: {r[2]})",
        }
        for r in rows
    ]

    return render_template(
        'family_trees.html',
        trees=trees,
        can_edit=bool(current_user),
        message=message,
        scope_text=scope_text,
        access_mask_text=access_mask_text,
        accessible_tree_names=accessible_tree_names,
        edit_tree=edit_tree,
        member_results=member_results,
        invite_rows=invite_rows,
    )


@app.route('/tree-preview')
def tree_preview():
    message = None
    tree_id_raw = request.args.get('tree_id', '').strip()
    tree_id = None
    query_ran = bool(tree_id_raw)
    current_user = get_current_user()
    tree_options = []
    visible_tree_ids = set()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            visible_rows = get_visible_tree_rows(cursor, current_user)
            tree_options = [
                {"id": row[0], "name": row[1], "surname": row[2]}
                for row in visible_rows
            ]
            visible_tree_ids = {row[0] for row in visible_rows}

    if tree_id_raw:
        try:
            tree_id = int(tree_id_raw)
        except ValueError:
            message = "Tree ID must be a number."
        else:
            if tree_id not in visible_tree_ids:
                message = "You do not have permission to preview this tree."

    if not tree_options and message is None:
        message = "No accessible family trees for current account."

    return render_template(
        'tree_preview.html',
        tree_id=tree_id,
        tree_options=tree_options,
        message=message,
        query_ran=query_ran,
    )


@app.get('/api/tree-preview/root')
def tree_preview_root_api():
    current_user = get_current_user()
    tree_id_raw = request.args.get('tree_id', '').strip()
    root_member_id_raw = request.args.get('root_member_id', '').strip()

    if not tree_id_raw:
        return jsonify({"ok": False, "error": "Tree ID is required."}), 400
    try:
        tree_id = int(tree_id_raw)
    except ValueError:
        return jsonify({"ok": False, "error": "Tree ID must be a number."}), 400

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if not can_access_tree(cursor, current_user, tree_id):
                return jsonify({"ok": False, "error": "You do not have permission to preview this tree."}), 403

            if root_member_id_raw:
                try:
                    root_member_id = int(root_member_id_raw)
                except ValueError:
                    return jsonify({"ok": False, "error": "Root member ID must be a number."}), 400
                root_row = fetch_person_row_in_tree(cursor, tree_id, root_member_id)
                if root_row is None:
                    return jsonify({"ok": False, "error": f"Root member {root_member_id} is not in tree {tree_id}."}), 404
            else:
                root_row = fetch_default_root_row(cursor, tree_id)
                if root_row is None:
                    return jsonify({"ok": False, "error": "No members found in this tree."}), 404

            root_id, root_name, root_generation = root_row
            has_children = root_id in fetch_has_children_ids(cursor, tree_id, [root_id])
            has_spouses = root_id in fetch_has_spouse_ids(cursor, [root_id])
            root_node = format_internal_node(
                root_id,
                root_name,
                root_generation,
                has_children=has_children,
                has_spouses=has_spouses,
            )

    return jsonify({"ok": True, "tree_id": tree_id, "root": root_node})


@app.get('/api/tree-preview/node/<int:person_id>/expand')
def tree_preview_node_expand_api(person_id):
    current_user = get_current_user()
    tree_id_raw = request.args.get('tree_id', '').strip()
    if not tree_id_raw:
        return jsonify({"ok": False, "error": "Tree ID is required."}), 400
    try:
        tree_id = int(tree_id_raw)
    except ValueError:
        return jsonify({"ok": False, "error": "Tree ID must be a number."}), 400

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if not can_access_tree(cursor, current_user, tree_id):
                return jsonify({"ok": False, "error": "You do not have permission to preview this tree."}), 403

            node_row = fetch_person_row_in_tree(cursor, tree_id, person_id)
            if node_row is None:
                return jsonify({"ok": False, "error": f"Member {person_id} is not in tree {tree_id}."}), 404

            cursor.execute(
                """
                SELECT DISTINCT
                    CASE WHEN r.person1_id = %s THEN p2.person_id ELSE p1.person_id END AS spouse_id,
                    CASE WHEN r.person1_id = %s THEN p2.name ELSE p1.name END AS spouse_name,
                    CASE WHEN r.person1_id = %s THEN p2.generation ELSE p1.generation END AS spouse_generation
                FROM "Relationship" r
                JOIN "Person" p1 ON p1.person_id = r.person1_id
                JOIN "Person" p2 ON p2.person_id = r.person2_id
                WHERE r.rel_type = 'spouse'
                  AND (r.person1_id = %s OR r.person2_id = %s)
                ORDER BY spouse_id
                """,
                (person_id, person_id, person_id, person_id, person_id),
            )
            spouse_rows = cursor.fetchall()
            spouses = [format_spouse_node(row[0], row[1], row[2]) for row in spouse_rows]

            cursor.execute(
                """
                SELECT c.person_id, c.name, c.generation
                FROM "Relationship" r
                JOIN "Person" c ON c.person_id = r.person2_id
                WHERE r.rel_type = 'parent'
                  AND r.person1_id = %s
                  AND c.tree_id = %s
                ORDER BY c.generation NULLS LAST, c.person_id
                """,
                (person_id, tree_id),
            )
            child_rows = cursor.fetchall()
            child_ids = [row[0] for row in child_rows]
            child_has_children = fetch_has_children_ids(cursor, tree_id, child_ids)
            child_has_spouses = fetch_has_spouse_ids(cursor, child_ids)
            children = [
                format_internal_node(
                    row[0],
                    row[1],
                    row[2],
                    has_children=row[0] in child_has_children,
                    has_spouses=row[0] in child_has_spouses,
                )
                for row in child_rows
            ]

    return jsonify({"ok": True, "node_id": person_id, "spouses": spouses, "children": children})


@app.get('/api/ancestor-preview/root')
def ancestor_preview_root_api():
    current_user = get_current_user()
    person_id_raw = request.args.get('person_id', '').strip()
    if not person_id_raw:
        return jsonify({"ok": False, "error": "Person ID is required."}), 400

    try:
        person_id = int(person_id_raw)
        if person_id < 1:
            raise ValueError
    except ValueError:
        return jsonify({"ok": False, "error": "Person ID must be a positive number."}), 400

    max_depth, depth_error = parse_optional_max_depth(request.args.get('max_depth'))
    if depth_error:
        return jsonify({"ok": False, "error": depth_error}), 400

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT person_id, name, generation, tree_id
                FROM "Person"
                WHERE person_id = %s
                """,
                (person_id,),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({"ok": False, "error": f"Person {person_id} not found."}), 404

            if not can_access_tree(cursor, current_user, row[3]):
                return jsonify({"ok": False, "error": "You do not have permission to view this person."}), 403

            has_parents = False
            if max_depth is None or max_depth > 0:
                cursor.execute(
                    """
                    SELECT 1
                    FROM "Relationship"
                    WHERE rel_type = 'parent'
                      AND person2_id = %s
                    LIMIT 1
                    """,
                    (person_id,),
                )
                has_parents = cursor.fetchone() is not None

    root_node = format_ancestor_preview_node(
        row[0],
        row[1],
        row[2],
        depth=0,
        has_parents=has_parents,
        path_ids=[row[0]],
    )
    return jsonify({"ok": True, "root": root_node, "max_depth": max_depth})


@app.get('/api/ancestor-preview/node/<int:person_id>/expand')
def ancestor_preview_node_expand_api(person_id):
    current_user = get_current_user()
    root_id_raw = request.args.get('root_id', '').strip()
    if not root_id_raw:
        return jsonify({"ok": False, "error": "Root ID is required."}), 400
    try:
        root_id = int(root_id_raw)
        if root_id < 1:
            raise ValueError
    except ValueError:
        return jsonify({"ok": False, "error": "Root ID must be a positive number."}), 400

    max_depth, depth_error = parse_optional_max_depth(request.args.get('max_depth'))
    if depth_error:
        return jsonify({"ok": False, "error": depth_error}), 400

    path_ids, path_error = parse_path_ids(request.args.get('path'))
    if path_error:
        return jsonify({"ok": False, "error": path_error}), 400
    if path_ids[0] != root_id:
        return jsonify({"ok": False, "error": "Path must start from root ID."}), 400
    if path_ids[-1] != person_id:
        return jsonify({"ok": False, "error": "Path does not match requested node."}), 400

    current_depth = len(path_ids) - 1
    if max_depth is not None and current_depth >= max_depth:
        return jsonify({"ok": True, "node_id": person_id, "parents": []})

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT tree_id
                FROM "Person"
                WHERE person_id = %s
                """,
                (root_id,),
            )
            root_row = cursor.fetchone()
            if not root_row:
                return jsonify({"ok": False, "error": f"Root person {root_id} not found."}), 404

            if not can_access_tree(cursor, current_user, root_row[0]):
                return jsonify({"ok": False, "error": "You do not have permission to view this person."}), 403

            if not is_valid_ancestor_chain(cursor, path_ids):
                return jsonify({"ok": False, "error": "Invalid ancestor path."}), 400

            cursor.execute(
                """
                SELECT p.person_id, p.name, p.generation
                FROM "Relationship" r
                JOIN "Person" p ON p.person_id = r.person1_id
                WHERE r.rel_type = 'parent'
                  AND r.person2_id = %s
                ORDER BY p.person_id
                """,
                (person_id,),
            )
            parent_rows = cursor.fetchall()

            path_set = set(path_ids)
            filtered_rows = [row for row in parent_rows if row[0] not in path_set]
            parent_ids = [row[0] for row in filtered_rows]
            next_depth = current_depth + 1

            parent_has_parents = set()
            if parent_ids and (max_depth is None or next_depth < max_depth):
                cursor.execute(
                    """
                    SELECT DISTINCT person2_id
                    FROM "Relationship"
                    WHERE rel_type = 'parent'
                      AND person2_id = ANY(%s)
                    """,
                    (parent_ids,),
                )
                parent_has_parents = {row[0] for row in cursor.fetchall()}

    parents = [
        format_ancestor_preview_node(
            row[0],
            row[1],
            row[2],
            depth=next_depth,
            has_parents=(row[0] in parent_has_parents),
            path_ids=path_ids + [row[0]],
        )
        for row in filtered_rows
    ]

    return jsonify({"ok": True, "node_id": person_id, "parents": parents})


@app.get('/api/patriline-preview/root')
def patriline_preview_root_api():
    current_user = get_current_user()
    person_id_raw = request.args.get('person_id', '').strip()
    if not person_id_raw:
        return jsonify({"ok": False, "error": "Person ID is required."}), 400

    try:
        person_id = int(person_id_raw)
        if person_id < 1:
            raise ValueError
    except ValueError:
        return jsonify({"ok": False, "error": "Person ID must be a positive number."}), 400

    max_depth, depth_error = parse_optional_max_depth(request.args.get('max_depth'))
    if depth_error:
        return jsonify({"ok": False, "error": depth_error}), 400

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT person_id, name, generation, gender, tree_id
                FROM "Person"
                WHERE person_id = %s
                """,
                (person_id,),
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({"ok": False, "error": f"Person {person_id} not found."}), 404

            if not can_access_tree(cursor, current_user, row[4]):
                return jsonify({"ok": False, "error": "You do not have permission to view this person."}), 403

            visible_tree_ids = get_visible_tree_ids(cursor, current_user)

            has_children = False
            if max_depth is None or max_depth > 0:
                cursor.execute(
                    """
                    SELECT 1
                    FROM "Relationship" r
                    JOIN "Person" c ON c.person_id = r.person2_id
                    WHERE r.rel_type = 'parent'
                      AND r.person1_id = %s
                      AND c.tree_id = ANY(%s)
                    LIMIT 1
                    """,
                    (person_id, list(visible_tree_ids)),
                )
                has_children = cursor.fetchone() is not None

    root_node = format_descendant_preview_node(
        row[0],
        row[1],
        row[2],
        row[3],
        depth=0,
        has_children=has_children,
        path_ids=[row[0]],
    )
    return jsonify({"ok": True, "root": root_node, "max_depth": max_depth})


@app.get('/api/patriline-preview/node/<int:person_id>/expand')
def patriline_preview_node_expand_api(person_id):
    current_user = get_current_user()
    root_id_raw = request.args.get('root_id', '').strip()
    if not root_id_raw:
        return jsonify({"ok": False, "error": "Root ID is required."}), 400
    try:
        root_id = int(root_id_raw)
        if root_id < 1:
            raise ValueError
    except ValueError:
        return jsonify({"ok": False, "error": "Root ID must be a positive number."}), 400

    max_depth, depth_error = parse_optional_max_depth(request.args.get('max_depth'))
    if depth_error:
        return jsonify({"ok": False, "error": depth_error}), 400

    path_ids, path_error = parse_path_ids(request.args.get('path'))
    if path_error:
        return jsonify({"ok": False, "error": path_error}), 400
    if path_ids[0] != root_id:
        return jsonify({"ok": False, "error": "Path must start from root ID."}), 400
    if path_ids[-1] != person_id:
        return jsonify({"ok": False, "error": "Path does not match requested node."}), 400

    current_depth = len(path_ids) - 1
    if max_depth is not None and current_depth >= max_depth:
        return jsonify({"ok": True, "node_id": person_id, "children": []})

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT tree_id
                FROM "Person"
                WHERE person_id = %s
                """,
                (root_id,),
            )
            root_row = cursor.fetchone()
            if not root_row:
                return jsonify({"ok": False, "error": f"Root person {root_id} not found."}), 404

            if not can_access_tree(cursor, current_user, root_row[0]):
                return jsonify({"ok": False, "error": "You do not have permission to view this person."}), 403

            if not is_valid_descendant_chain(cursor, path_ids):
                return jsonify({"ok": False, "error": "Invalid descendant path."}), 400

            visible_tree_ids = get_visible_tree_ids(cursor, current_user)
            if not visible_tree_ids:
                return jsonify({"ok": True, "node_id": person_id, "children": []})

            cursor.execute(
                """
                SELECT child.person_id, child.name, child.generation, child.gender
                FROM "Relationship" r
                JOIN "Person" child ON child.person_id = r.person2_id
                WHERE r.rel_type = 'parent'
                  AND r.person1_id = %s
                  AND child.tree_id = ANY(%s)
                ORDER BY child.person_id
                """,
                (person_id, list(visible_tree_ids)),
            )
            child_rows = cursor.fetchall()

            path_set = set(path_ids)
            filtered_rows = [row for row in child_rows if row[0] not in path_set]
            child_ids = [row[0] for row in filtered_rows]
            next_depth = current_depth + 1

            child_has_children = set()
            if child_ids and (max_depth is None or next_depth < max_depth):
                cursor.execute(
                    """
                    SELECT DISTINCT r.person1_id
                    FROM "Relationship" r
                    JOIN "Person" child ON child.person_id = r.person2_id
                    WHERE r.rel_type = 'parent'
                      AND r.person1_id = ANY(%s)
                      AND child.tree_id = ANY(%s)
                    """,
                    (child_ids, list(visible_tree_ids)),
                )
                child_has_children = {row[0] for row in cursor.fetchall()}

    children = [
        format_descendant_preview_node(
            row[0],
            row[1],
            row[2],
            row[3],
            depth=next_depth,
            has_children=(row[0] in child_has_children),
            path_ids=path_ids + [row[0]],
        )
        for row in filtered_rows
    ]

    return jsonify({"ok": True, "node_id": person_id, "children": children})


@app.route('/family-trees/<int:tree_id>/export')
def export_family_tree(tree_id):
    current_user = get_current_user()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if not can_access_tree(cursor, current_user, tree_id):
                abort(403, description="You do not have permission to export this family tree.")

            cursor.execute(
                """
                SELECT tree_id, name, surname, revision_date, creator_id
                FROM "FamilyTree"
                WHERE tree_id = %s
                """,
                (tree_id,),
            )
            tree_row = cursor.fetchone()
            if not tree_row:
                abort(404, description=f"Family tree {tree_id} not found.")

            cursor.execute(
                """
                SELECT person_id, tree_id, name, gender, birth_date, generation, death_date
                FROM "Person"
                WHERE tree_id = %s
                ORDER BY person_id
                """,
                (tree_id,),
            )
            people_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT r.person1_id, r.person2_id, r.rel_type
                FROM "Relationship" r
                JOIN "Person" p1 ON p1.person_id = r.person1_id
                JOIN "Person" p2 ON p2.person_id = r.person2_id
                WHERE p1.tree_id = %s AND p2.tree_id = %s
                ORDER BY r.person1_id, r.person2_id, r.rel_type
                """,
                (tree_id, tree_id),
            )
            rel_rows = cursor.fetchall()

    export_buffer = io.BytesIO()
    with zipfile.ZipFile(export_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        tree_csv = io.StringIO(newline="")
        tree_writer = csv.writer(tree_csv)
        tree_writer.writerow(["tree_id", "name", "surname", "revision_date", "creator_id"])
        tree_writer.writerow(tree_row)
        zf.writestr("family_tree.csv", tree_csv.getvalue())

        people_csv = io.StringIO(newline="")
        people_writer = csv.writer(people_csv)
        people_writer.writerow(["person_id", "tree_id", "name", "gender", "birth_date", "generation", "death_date"])
        people_writer.writerows(people_rows)
        zf.writestr("person.csv", people_csv.getvalue())

        rel_csv = io.StringIO(newline="")
        rel_writer = csv.writer(rel_csv)
        rel_writer.writerow(["person1_id", "person2_id", "rel_type"])
        rel_writer.writerows(rel_rows)
        zf.writestr("relationship.csv", rel_csv.getvalue())

    export_buffer.seek(0)
    return send_file(
        export_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"family_tree_{tree_id}_export.zip",
    )


@app.route('/queries')
def queries():
    ancestor_result = []
    ancestor_tree = None
    ancestor_message = None
    relationship_result = None
    ancestor_time_ms = None
    relationship_time_ms = None
    ancestor_member_id = request.args.get("ancestor_member_id")
    from_id = request.args.get("from_id")
    to_id = request.args.get("to_id")
    relationship_engine = request.args.get("relationship_engine", "sql")
    relationship_message = None
    relationship_notice = None

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if ancestor_member_id:
                try:
                    ancestor_member_id_int = int(ancestor_member_id)
                except ValueError:
                    ancestor_message = "Member ID must be a number."
                else:
                    cursor.execute(
                        'SELECT tree_id FROM "Person" WHERE person_id = %s',
                        (ancestor_member_id_int,),
                    )
                    tree_row = cursor.fetchone()
                    if not tree_row:
                        ancestor_message = f"Member {ancestor_member_id_int} not found."
                    elif not can_access_tree(cursor, get_current_user(), tree_row[0]):
                        ancestor_message = "You do not have permission to view this member."
                    else:
                        start_time = time.perf_counter()
                        ancestor_result = query_task_2_ancestors(ancestor_member_id_int, None)
                        ancestor_tree = build_ancestor_tree(cursor, ancestor_member_id_int)
                        ancestor_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            if from_id and to_id:
                try:
                    from_id_int = int(from_id)
                    to_id_int = int(to_id)
                except ValueError:
                    relationship_result = None
                else:
                    cursor.execute('SELECT tree_id FROM "Person" WHERE person_id = %s', (from_id_int,))
                    from_row = cursor.fetchone()
                    cursor.execute('SELECT tree_id FROM "Person" WHERE person_id = %s', (to_id_int,))
                    to_row = cursor.fetchone()
                    if not from_row or not to_row:
                        relationship_message = "One or both members do not exist."
                    elif not can_access_tree(cursor, get_current_user(), from_row[0]) or not can_access_tree(cursor, get_current_user(), to_row[0]):
                        relationship_message = "You do not have permission to view one or both members."
                    else:
                        start_time = time.perf_counter()
                        if relationship_engine == "python":
                            relationship_result = query_relationship_path_python(from_id_int, to_id_int)
                        else:
                            try:
                                relationship_result = query_relationship_path(
                                    from_id_int,
                                    to_id_int,
                                    timeout_ms=RELATIONSHIP_SQL_TIMEOUT_MS,
                                )
                            except psycopg2.Error as err:
                                if getattr(err, "pgcode", None) == "57014":
                                    relationship_result = query_relationship_path_python(from_id_int, to_id_int)
                                    relationship_engine = "python"
                                    relationship_notice = (
                                        f"SQL recursive query exceeded {RELATIONSHIP_SQL_TIMEOUT_MS} ms; "
                                        "switched to Python engine automatically."
                                    )
                                else:
                                    raise
                        relationship_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return render_template(
        'queries.html',
        ancestor_result=ancestor_result,
        ancestor_tree=ancestor_tree,
        ancestor_message=ancestor_message,
        relationship_result=relationship_result,
        relationship_message=relationship_message,
        relationship_notice=relationship_notice,
        relationship_engine=relationship_engine,
        ancestor_time_ms=ancestor_time_ms,
        relationship_time_ms=relationship_time_ms,
    )


@app.route('/tasks/1')
def task_1():
    message = None
    spouse_gate_note = None
    person = None
    parents = []
    spouses = []
    siblings = []
    children = []
    name_search_message = None
    name_candidates = []

    person_id_raw = request.args.get('person_id', '').strip()
    name_char_1 = request.args.get('name_char_1', '').strip()[:1]
    name_char_2 = request.args.get('name_char_2', '').strip()[:1]
    name_char_3 = request.args.get('name_char_3', '').strip()[:1]
    name_search_ran = bool(name_char_1 or name_char_2 or name_char_3)
    current_user = get_current_user()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if name_search_ran:
                name_candidates = query_task_1_name_candidates(
                    cursor,
                    current_user,
                    name_char_1,
                    name_char_2,
                    name_char_3,
                )
                if not name_candidates:
                    name_search_message = "No member matched the provided name characters in visible trees."

            if person_id_raw:
                try:
                    person_id = int(person_id_raw)
                except ValueError:
                    message = "Person ID must be a number."
                else:
                    cursor.execute('SELECT tree_id FROM "Person" WHERE person_id = %s', (person_id,))
                    row = cursor.fetchone()
                    if not row:
                        message = f"Person {person_id} not found."
                    elif not can_access_tree(cursor, current_user, row[0]):
                        message = "You do not have permission to view this person."
                    else:
                        (
                            message,
                            person,
                            parents,
                            spouses,
                            siblings,
                            children,
                            spouse_gate_note,
                        ) = query_task_1_kin_radius(person_id)

    return render_template(
        'task_1.html',
        message=message,
        person=person,
        parents=parents,
        spouses=spouses,
        siblings=siblings,
        children=children,
        spouse_gate_note=spouse_gate_note,
        name_char_1=name_char_1,
        name_char_2=name_char_2,
        name_char_3=name_char_3,
        name_search_ran=name_search_ran,
        name_search_message=name_search_message,
        name_candidates=name_candidates,
    )


@app.route('/tasks/2')
def task_2():
    message = None
    query_ran = False
    ancestors = []
    ancestor_total_count = 0
    ancestor_total_pages = 0
    ancestor_page_size = 200
    ancestor_page = 1
    ancestor_root_person_id = None
    ancestor_max_depth = None
    ancestor_time_ms = None
    person_id_raw = request.args.get('person_id', '').strip()
    max_depth_raw = request.args.get('max_depth', '').strip()
    page_raw = request.args.get('page', '1').strip()
    person_id = None
    max_depth = None

    try:
        ancestor_page = int(page_raw)
        if ancestor_page < 1:
            raise ValueError
    except ValueError:
        ancestor_page = 1

    if person_id_raw:
        query_ran = True
        try:
            person_id = int(person_id_raw)
            if person_id < 1:
                raise ValueError
        except ValueError:
            message = "Person ID must be a positive number."
        else:
            max_depth, depth_error = parse_optional_max_depth(max_depth_raw)
            if depth_error:
                message = depth_error
        if message is None:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT tree_id FROM "Person" WHERE person_id = %s', (person_id,))
                    row = cursor.fetchone()
                    if not row:
                        message = f"Person {person_id} not found."
                    elif not can_access_tree(cursor, get_current_user(), row[0]):
                        message = "You do not have permission to view this person."
                    else:
                        ancestor_root_person_id = person_id
                        ancestor_max_depth = max_depth
                        start_time = time.perf_counter()
                        all_ancestors = query_task_2_ancestors(person_id, max_depth)
                        ancestor_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
                        ancestor_total_count = len(all_ancestors)
                        if ancestor_total_count > 0:
                            ancestor_total_pages = (ancestor_total_count + ancestor_page_size - 1) // ancestor_page_size
                            if ancestor_page > ancestor_total_pages:
                                ancestor_page = ancestor_total_pages
                            start_idx = (ancestor_page - 1) * ancestor_page_size
                            end_idx = start_idx + ancestor_page_size
                            ancestors = all_ancestors[start_idx:end_idx]
                        else:
                            ancestors = []
                            ancestor_total_pages = 0

    return render_template(
        'task_2.html',
        message=message,
        query_ran=query_ran,
        ancestors=ancestors,
        ancestor_total_count=ancestor_total_count,
        ancestor_total_pages=ancestor_total_pages,
        ancestor_page_size=ancestor_page_size,
        ancestor_page=ancestor_page,
        ancestor_root_person_id=ancestor_root_person_id,
        ancestor_max_depth=ancestor_max_depth,
        ancestor_time_ms=ancestor_time_ms,
    )


@app.route('/tasks/3')
def task_3():
    message = None
    query_ran = False
    summary = None
    generation_stats = []
    current_user = get_current_user()
    tree_options = []
    visible_tree_ids = set()
    tree_id = request.args.get('tree_id', '').strip()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            visible_rows = get_visible_tree_rows(cursor, current_user)
            tree_options = [
                {"id": row[0], "name": row[1], "surname": row[2]}
                for row in visible_rows
            ]
            visible_tree_ids = {row[0] for row in visible_rows}

    if tree_id:
        query_ran = True
        try:
            tree_id = int(tree_id)
        except ValueError:
            message = "Family tree ID must be a number."
        else:
            if tree_id not in visible_tree_ids:
                message = "You do not have permission to view this family tree."
            else:
                summary, generation_stats = query_task_3_longest_lived_generation(tree_id)

    return render_template(
        'task_3.html',
        message=message,
        query_ran=query_ran,
        summary=summary,
        generation_stats=generation_stats,
        tree_options=tree_options,
    )


@app.route('/tasks/4')
def task_4():
    message = None
    query_ran = False
    members = []
    current_user = get_current_user()
    tree_options = []
    visible_tree_ids = set()
    tree_id = request.args.get('tree_id', '').strip()
    min_age = request.args.get('min_age', '').strip()
    max_age = request.args.get('max_age', '').strip()
    married = request.args.get('married', 'any')
    has_children = request.args.get('has_children', 'any')
    alive = request.args.get('alive', 'any')
    gender = request.args.get('gender', 'any').strip().lower()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            visible_rows = get_visible_tree_rows(cursor, current_user)
            tree_options = [
                {"id": row[0], "name": row[1], "surname": row[2]}
                for row in visible_rows
            ]
            visible_tree_ids = {row[0] for row in visible_rows}

    if tree_id:
        query_ran = True
        try:
            tree_id = int(tree_id)
        except ValueError:
            message = "Family tree ID must be a number."
        else:
            if tree_id not in visible_tree_ids:
                message = "You do not have permission to view this family tree."

        if message is None and min_age:
            try:
                min_age = int(min_age)
                if min_age < 0:
                    raise ValueError
            except ValueError:
                message = "Min age must be a non-negative number."

        if message is None and max_age:
            try:
                max_age = int(max_age)
                if max_age < 0:
                    raise ValueError
            except ValueError:
                message = "Max age must be a non-negative number."

        if message is None:
            if gender not in {'any', 'male', 'female', 'other'}:
                message = "Gender filter must be one of: any, male, female, other."

        if message is None:
            filters = {
                "tree_id": tree_id,
                "min_age": min_age if min_age != '' else None,
                "max_age": max_age if max_age != '' else None,
                "married": married,
                "has_children": has_children,
                "alive": alive,
                "gender": gender,
            }
            members = query_task_4_filter_members(filters)

    return render_template(
        'task_4.html',
        message=message,
        query_ran=query_ran,
        members=members,
        tree_options=tree_options,
    )


@app.route('/tasks/5')
def task_5():
    message = None
    query_ran = False
    early_births = []
    current_user = get_current_user()
    tree_options = []
    visible_tree_ids = set()
    tree_id = request.args.get('tree_id', '').strip()
    generation_depth = request.args.get('generation_depth', '').strip()

    with get_connection() as conn:
        with conn.cursor() as cursor:
            visible_rows = get_visible_tree_rows(cursor, current_user)
            tree_options = [
                {"id": row[0], "name": row[1], "surname": row[2]}
                for row in visible_rows
            ]
            visible_tree_ids = {row[0] for row in visible_rows}

    if tree_id:
        query_ran = True
        try:
            tree_id = int(tree_id)
        except ValueError:
            message = "Family tree ID must be a number."
        else:
            if tree_id not in visible_tree_ids:
                message = "You do not have permission to view this family tree."
            else:
                if generation_depth:
                    try:
                        generation_depth = int(generation_depth)
                        if generation_depth < 0:
                            raise ValueError
                    except ValueError:
                        message = "Generation depth must be a non-negative number."
                else:
                    generation_depth = None

        if message is None:
            early_births = query_task_5_early_births(tree_id, generation_depth)

    return render_template(
        'task_5.html',
        message=message,
        query_ran=query_ran,
        early_births=early_births,
        tree_options=tree_options,
    )


@app.route('/tasks/6')
def task_6():
    message = None
    query_ran = False
    descendants = []
    descendant_root_person_id = None
    descendant_max_depth = None
    descendant_time_ms = None
    person_id_raw = request.args.get('person_id', '').strip()
    max_depth_raw = request.args.get('max_depth', '').strip()
    person_id = None
    max_depth = None

    if person_id_raw:
        query_ran = True
        try:
            person_id = int(person_id_raw)
            if person_id < 1:
                raise ValueError
        except ValueError:
            message = "Person ID must be a positive number."
        else:
            max_depth, depth_error = parse_optional_max_depth(max_depth_raw)
            if depth_error:
                message = depth_error

        if message is None:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT tree_id
                        FROM "Person"
                        WHERE person_id = %s
                        """,
                        (person_id,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        message = f"Person {person_id} not found."
                    elif not can_access_tree(cursor, get_current_user(), row[0]):
                        message = "You do not have permission to view this person."
                    else:
                        visible_tree_ids = get_visible_tree_ids(cursor, get_current_user())
                        descendant_root_person_id = person_id
                        descendant_max_depth = max_depth
                        start_time = time.perf_counter()
                        descendants = query_task_6_descendants(person_id, max_depth, visible_tree_ids)
                        descendant_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return render_template(
        'task_6.html',
        message=message,
        query_ran=query_ran,
        descendants=descendants,
        descendant_root_person_id=descendant_root_person_id,
        descendant_max_depth=descendant_max_depth,
        descendant_time_ms=descendant_time_ms,
    )


if __name__ == '__main__':
    app.run(
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "5000")),
        debug=os.getenv("APP_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"},
    )
