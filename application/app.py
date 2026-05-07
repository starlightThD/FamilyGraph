import os
from collections import defaultdict

import psycopg2
from flask import Flask, render_template, request

app = Flask(__name__)


def get_viewer_role():
    """
    Demo access switch:
    - /...?as=admin -> admin mode
    - default -> guest mode
    """
    return request.args.get('as', 'guest').strip().lower()


def is_admin_view():
    return get_viewer_role() == 'admin'


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fgdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


@app.context_processor
def inject_access_context():
    role = get_viewer_role()
    return {
        'viewer_role': 'admin' if role == 'admin' else 'guest',
        'can_edit': role == 'admin',
    }


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/dashboard')
def dashboard():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM "Person"')
            total_members = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM \"Person\" WHERE gender = 'male'")
            male_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM \"Person\" WHERE gender = 'female'")
            female_count = cursor.fetchone()[0]
    stats = {"total_members": total_members, "male_count": male_count, "female_count": female_count}
    return render_template('dashboard.html', stats=stats)


@app.route('/family-trees', methods=['GET', 'POST'])
def family_trees():
    message = None
    if request.method == 'POST':
        if not is_admin_view():
            message = "当前身份不是管理员，无法执行写操作。"
        else:
            tree_name = request.form.get('tree_name', '').strip()
            surname = request.form.get('surname', '').strip() or "未设置"
            creator_id = int(request.form.get('creator_id', '1') or 1)
            if not tree_name:
                message = "族谱名称不能为空。"
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
                message = "族谱新增成功。"

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
    trees = [{"id": r[0], "name": r[1], "role": f"创建者：{r[3]}（{r[2]}氏）"} for r in rows]
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
        sample_branch = {"name": "暂无数据", "children": []}
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


if __name__ == '__main__':
    app.run(debug=True)
