import os
from collections import defaultdict

import psycopg2
from flask import Flask, render_template, request, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

TABLES = [
	"User",
	"Person",
	"FamilyTree",
	"Relationship",
	"KinshipClosure",
]

def get_current_user():
    if 'user_id' not in session:
        return None
    return {
        'user_id': session.get('user_id'),
        'username': session.get('username'),
        'is_admin': session.get('is_admin', False),
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


def query_task_2_ancestors(person_id, max_depth):
    # TODO: Purpose: fetch all ancestors of person_id, optionally limited by max_depth.
    # TODO: Flow: validate inputs -> execute SQL (closure table or recursive CTE) -> map rows -> return list.
    return []


def query_task_3_longest_lived_generation(tree_id):
    # TODO: Purpose: find the generation depth with the highest average lifespan in a tree.
    # TODO: Flow: compute per-depth avg lifespan -> pick max -> return summary and per-depth stats.
    summary = {
        "best_depth": None,
        "avg_lifespan": None,
        "member_count": None,
    }
    return summary, []


def query_task_4_filter_members(filters):
    # TODO: Purpose: filter members by age, marital status, children, and living status.
    # TODO: Flow: build SQL with optional filters -> execute -> return list of member dicts.
    return []


def query_task_5_early_births(tree_id, generation_depth):
    # TODO: Purpose: find members born earlier than their generation average birth year.
    # TODO: Flow: compute generation averages -> compare each member -> return qualifying rows.
    return []


@app.context_processor
def inject_access_context():
    user = get_current_user()
    return {
        'viewer_role': 'admin' if user and user.get('is_admin') else 'guest',
        'can_edit': bool(user and user.get('is_admin')),
        'current_user': user,
    }


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    message = None
    if request.method == 'POST':
        identity = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not identity or not password:
            message = "Please enter your username/email and password."
        else:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT user_id, username, password_hash, is_admin
                        FROM "User"
                        WHERE username = %s OR email = %s
                        LIMIT 1
                        """,
                        (identity, identity),
                    )
                    row = cursor.fetchone()
            if not row or not check_password_hash(row[2], password):
                message = "Invalid username/email or password."
            else:
                session.clear()
                session['user_id'] = row[0]
                session['username'] = row[1]
                session['is_admin'] = row[3]
                return redirect(url_for('dashboard'))
    return render_template('login.html', message=message)


@app.route('/register', methods=['GET', 'POST'])
def register():
    message = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not username or not email or not password:
            message = "Please complete all required fields."
        elif password != confirm_password:
            message = "Passwords do not match."
        else:
            password_hash = generate_password_hash(password)
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
                            RETURNING user_id, is_admin
                            """,
                            (username, password_hash, email),
                        )
                        row = cursor.fetchone()
                        conn.commit()
                        session.clear()
                        session['user_id'] = row[0]
                        session['username'] = username
                        session['is_admin'] = row[1]
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
    if request.method == 'POST':
        if not is_admin_view():
            message = "You are not an admin and cannot perform write operations."
        else:
            tree_name = request.form.get('tree_name', '').strip()
            surname = request.form.get('surname', '').strip() or "Unspecified"
            current_user = get_current_user()
            creator_id = current_user['user_id'] if current_user else 1
            if not tree_name:
                message = "Tree name cannot be empty."
            else:
                with get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO "FamilyTree" (name, surname, revision_date, creator_id)
                            VALUES (%s, %s, CURRENT_DATE, %s)
                            """,
                            (tree_name, surname, creator_id),
                        )
                        conn.commit()
                message = "Family tree created successfully."

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.tree_id, f.name, f.surname, u.username
                FROM "FamilyTree" f
                JOIN "User" u ON u.user_id = f.creator_id
                ORDER BY f.tree_id
                """
            )
            rows = cursor.fetchall()
    trees = [{"id": r[0], "name": r[1], "role": f"Creator: {r[3]} (Surname: {r[2]})"} for r in rows]
    return render_template('family_trees.html', trees=trees, can_edit=is_admin_view(), message=message)


@app.route('/tree-preview')
def tree_preview():
    tree_id = int(request.args.get('tree_id', '1'))
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT person_id, name FROM "Person" WHERE tree_id = %s ORDER BY person_id',
                (tree_id,),
            )
            people = cursor.fetchall()
            cursor.execute(
                """
                SELECT person1_id, person2_id
                FROM "Relationship"
                WHERE rel_type = 'parent'
                """
            )
            edges = cursor.fetchall()

    if not people:
        sample_branch = {"name": "No data", "children": []}
        return render_template('tree_preview.html', sample_branch=sample_branch)

    name_by_id = {pid: name for pid, name in people}
    children_map = defaultdict(list)
    has_parent = set()
    for parent_id, child_id in edges:
        if parent_id in name_by_id and child_id in name_by_id:
            children_map[parent_id].append(child_id)
            has_parent.add(child_id)
    roots = [pid for pid, _ in people if pid not in has_parent]
    root_id = roots[0] if roots else people[0][0]

    def build_node(person_id):
        return {
            "name": name_by_id[person_id],
            "children": [build_node(cid) for cid in children_map.get(person_id, [])],
        }

    sample_branch = build_node(root_id)
    return render_template('tree_preview.html', sample_branch=sample_branch)


@app.route('/queries')
def queries():
    ancestor_result = []
    relationship_result = []
    ancestor_member_id = request.args.get("ancestor_member_id")
    from_id = request.args.get("from_id")
    to_id = request.args.get("to_id")

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if ancestor_member_id:
                cursor.execute(
                    """
                    SELECT kc.ancestor_id, p.name, kc.depth
                    FROM "KinshipClosure" kc
                    JOIN "Person" p ON p.person_id = kc.ancestor_id
                    WHERE kc.descendant_id = %s
                    ORDER BY kc.depth, kc.ancestor_id
                    """,
                    (int(ancestor_member_id),),
                )
                ancestor_result = cursor.fetchall()
            if from_id and to_id:
                cursor.execute(
                    """
                    SELECT rel_type
                    FROM "Relationship"
                    WHERE person1_id = %s AND person2_id = %s
                    """,
                    (int(from_id), int(to_id)),
                )
                relationship_result = cursor.fetchall()

    return render_template(
        'queries.html',
        ancestor_result=ancestor_result,
        relationship_result=relationship_result,
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

    person_id = request.args.get('person_id')
    if person_id:
        try:
            person_id = int(person_id)
        except ValueError:
            message = "Person ID must be a number."
        else:
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
                    else:
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
                        father_row = cursor.fetchone()
                        if father_row:
                            father_id = father_row[0]
                            cursor.execute(
                                """
                                SELECT p.person_id, p.name
                                FROM "Relationship" r
                                JOIN "Person" p ON p.person_id = r.person2_id
                                WHERE r.rel_type = 'parent'
                                  AND r.person1_id = %s
                                  AND p.person_id <> %s
                                ORDER BY p.person_id
                                """,
                                (father_id, person_id),
                            )
                            siblings = cursor.fetchall()

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

    return render_template(
        'task_1.html',
        message=message,
        person=person,
        parents=parents,
        spouses=spouses,
        siblings=siblings,
        children=children,
        spouse_gate_note=spouse_gate_note,
    )


@app.route('/tasks/2')
def task_2():
    message = None
    query_ran = False
    ancestors = []
    person_id = request.args.get('person_id', '').strip()
    max_depth = request.args.get('max_depth', '').strip()

    if person_id:
        query_ran = True
        try:
            person_id = int(person_id)
        except ValueError:
            message = "Person ID must be a number."
        else:
            if max_depth:
                try:
                    max_depth = int(max_depth)
                    if max_depth < 1:
                        raise ValueError
                except ValueError:
                    message = "Max depth must be a positive number."
            else:
                max_depth = None
        if message is None:
            ancestors = query_task_2_ancestors(person_id, max_depth)

    return render_template(
        'task_2.html',
        message=message,
        query_ran=query_ran,
        ancestors=ancestors,
    )


@app.route('/tasks/3')
def task_3():
    message = None
    query_ran = False
    summary = None
    generation_stats = []
    tree_id = request.args.get('tree_id', '').strip()

    if tree_id:
        query_ran = True
        try:
            tree_id = int(tree_id)
        except ValueError:
            message = "Family tree ID must be a number."
        else:
            summary, generation_stats = query_task_3_longest_lived_generation(tree_id)

    return render_template(
        'task_3.html',
        message=message,
        query_ran=query_ran,
        summary=summary,
        generation_stats=generation_stats,
    )


@app.route('/tasks/4')
def task_4():
    message = None
    query_ran = False
    members = []
    tree_id = request.args.get('tree_id', '').strip()
    min_age = request.args.get('min_age', '').strip()
    max_age = request.args.get('max_age', '').strip()
    married = request.args.get('married', 'any')
    has_children = request.args.get('has_children', 'any')
    alive = request.args.get('alive', 'any')

    if tree_id:
        query_ran = True
        try:
            tree_id = int(tree_id)
        except ValueError:
            message = "Family tree ID must be a number."

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
            filters = {
                "tree_id": tree_id,
                "min_age": min_age if min_age != '' else None,
                "max_age": max_age if max_age != '' else None,
                "married": married,
                "has_children": has_children,
                "alive": alive,
            }
            members = query_task_4_filter_members(filters)

    return render_template(
        'task_4.html',
        message=message,
        query_ran=query_ran,
        members=members,
    )


@app.route('/tasks/5')
def task_5():
    message = None
    query_ran = False
    early_births = []
    tree_id = request.args.get('tree_id', '').strip()
    generation_depth = request.args.get('generation_depth', '').strip()

    if tree_id:
        query_ran = True
        try:
            tree_id = int(tree_id)
        except ValueError:
            message = "Family tree ID must be a number."
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
    )


if __name__ == '__main__':
    app.run(debug=True)
