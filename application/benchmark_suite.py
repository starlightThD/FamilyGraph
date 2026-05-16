#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import os
import statistics
import time
from pathlib import Path

get_connection = None
query_task_2_ancestors = None
query_task_6_descendants = None


TASK2_SQL_RECURSIVE = """
WITH RECURSIVE ancestor_walk AS (
    SELECT
        r.person1_id AS ancestor_id,
        1 AS depth,
        ARRAY[r.person2_id, r.person1_id] AS path
    FROM "Relationship" r
    WHERE r.rel_type = 'parent' AND r.person2_id = %s
    UNION ALL
    SELECT
        r.person1_id AS ancestor_id,
        aw.depth + 1 AS depth,
        aw.path || r.person1_id
    FROM ancestor_walk aw
    JOIN "Relationship" r
      ON r.rel_type = 'parent'
     AND r.person2_id = aw.ancestor_id
    WHERE NOT (r.person1_id = ANY(aw.path))
)
SELECT
    aw.ancestor_id,
    p.name,
    MIN(aw.depth) AS depth
FROM ancestor_walk aw
JOIN "Person" p ON p.person_id = aw.ancestor_id
GROUP BY aw.ancestor_id, p.name
HAVING (%s::INTEGER IS NULL OR MIN(aw.depth) <= %s::INTEGER)
ORDER BY MIN(aw.depth), aw.ancestor_id
"""


TASK6_SQL_RECURSIVE = """
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


def parse_args():
    parser = argparse.ArgumentParser(description="Run FamilyGraph benchmark suite.")
    parser.add_argument("--task2-person-id", type=int, default=15240)
    parser.add_argument("--task6-person-id", type=int, default=1524)
    parser.add_argument(
        "--task6-auto-pick",
        action="store_true",
        help="Auto-pick a task6 person with the most direct children in visible scope.",
    )
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--task6-scope",
        choices=["same-tree", "all-trees"],
        default="same-tree",
        help="Which tree IDs are visible for task6 benchmark.",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
        help="Directory where benchmark artifacts will be written.",
    )
    return parser.parse_args()


def load_app_api():
    global get_connection, query_task_2_ancestors, query_task_6_descendants
    if get_connection is not None:
        return
    from app import get_connection as _get_connection
    from app import query_task_2_ancestors as _query_task_2_ancestors
    from app import query_task_6_descendants as _query_task_6_descendants

    get_connection = _get_connection
    query_task_2_ancestors = _query_task_2_ancestors
    query_task_6_descendants = _query_task_6_descendants


def configure_default_db_env():
    # Keep benchmark defaults aligned with application/start.sh.
    os.environ.setdefault("DB_USER", os.getenv("USER", "postgres"))
    os.environ.setdefault("DB_PASSWORD", "")
    os.environ.setdefault("DB_HOST", "/var/run/postgresql")
    os.environ.setdefault("DB_PORT", "5432")
    os.environ.setdefault("DB_NAME", "fgdb")


def get_task6_visible_tree_ids(person_id, scope):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            if scope == "all-trees":
                cursor.execute('SELECT tree_id FROM "FamilyTree" ORDER BY tree_id')
                return [row[0] for row in cursor.fetchall()]
            cursor.execute('SELECT tree_id FROM "Person" WHERE person_id = %s', (person_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Person {person_id} not found for task6 scope resolution.")
            return [row[0]]


def pick_task6_person(visible_tree_ids):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    r.person1_id AS person_id,
                    COUNT(*) AS direct_children
                FROM "Relationship" r
                JOIN "Person" c ON c.person_id = r.person2_id
                WHERE r.rel_type = 'parent'
                  AND c.tree_id = ANY(%s)
                GROUP BY r.person1_id
                ORDER BY direct_children DESC, r.person1_id
                LIMIT 1
                """,
                (list(visible_tree_ids),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return int(row[0])


def run_sql_task2(person_id, max_depth):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(TASK2_SQL_RECURSIVE, (person_id, max_depth, max_depth))
            return cursor.fetchall()


def run_sql_task6(person_id, max_depth, visible_tree_ids):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                TASK6_SQL_RECURSIVE,
                (
                    person_id,
                    person_id,
                    list(visible_tree_ids),
                    list(visible_tree_ids),
                    max_depth,
                    max_depth,
                ),
            )
            return cursor.fetchall()


def save_explain(path, sql, params):
    explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE) {sql}"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(explain_sql, params)
            lines = [row[0] for row in cursor.fetchall()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def benchmark_case(case_name, fn, warmup, repeats):
    for _ in range(max(0, warmup)):
        fn()

    runs = []
    for i in range(1, repeats + 1):
        t0 = time.perf_counter()
        rows = fn()
        ms = (time.perf_counter() - t0) * 1000.0
        runs.append(
            {
                "case": case_name,
                "run": i,
                "ms": ms,
                "row_count": len(rows),
            }
        )
    return runs


def summarize_runs(runs):
    by_case = {}
    for row in runs:
        by_case.setdefault(row["case"], []).append(row)

    summary = []
    for case, rows in by_case.items():
        ms_values = [r["ms"] for r in rows]
        row_counts = [r["row_count"] for r in rows]
        summary.append(
            {
                "case": case,
                "runs": len(rows),
                "avg_ms": statistics.fmean(ms_values),
                "p95_ms": sorted(ms_values)[max(0, int(len(ms_values) * 0.95) - 1)],
                "min_ms": min(ms_values),
                "max_ms": max(ms_values),
                "row_count_min": min(row_counts),
                "row_count_max": max(row_counts),
            }
        )
    summary.sort(key=lambda x: x["case"])
    return summary


def write_raw_csv(path, runs):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["case", "run", "ms", "row_count"])
        writer.writeheader()
        for row in runs:
            writer.writerow(
                {
                    "case": row["case"],
                    "run": row["run"],
                    "ms": f"{row['ms']:.3f}",
                    "row_count": row["row_count"],
                }
            )


def write_summary_csv(path, summary):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case",
                "runs",
                "avg_ms",
                "p95_ms",
                "min_ms",
                "max_ms",
                "row_count_min",
                "row_count_max",
            ],
        )
        writer.writeheader()
        for row in summary:
            out = dict(row)
            for k in ("avg_ms", "p95_ms", "min_ms", "max_ms"):
                out[k] = f"{out[k]:.3f}"
            writer.writerow(out)


def write_summary_md(path, args, summary, task6_visible_tree_ids):
    lines = []
    lines.append("# Benchmark Summary")
    lines.append("")
    lines.append(f"- generated_at: {dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- task2_person_id: {args.task2_person_id}")
    lines.append(f"- task6_person_id: {args.task6_person_id}")
    lines.append(f"- max_depth: {args.max_depth}")
    lines.append(f"- warmup: {args.warmup}")
    lines.append(f"- repeats: {args.repeats}")
    lines.append(f"- task6_scope: {args.task6_scope}")
    lines.append(f"- task6_visible_tree_ids: {task6_visible_tree_ids}")
    lines.append("")
    lines.append(
        "| case | runs | avg_ms | p95_ms | min_ms | max_ms | row_count_min | row_count_max |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|"
    )
    for row in summary:
        lines.append(
            f"| {row['case']} | {row['runs']} | {row['avg_ms']:.3f} | {row['p95_ms']:.3f} | "
            f"{row['min_ms']:.3f} | {row['max_ms']:.3f} | {row['row_count_min']} | {row['row_count_max']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    configure_default_db_env()
    load_app_api()
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = Path(args.output_dir) / f"bench_{timestamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    task6_visible_tree_ids = get_task6_visible_tree_ids(args.task6_person_id, args.task6_scope)
    if args.task6_auto_pick:
        picked = pick_task6_person(task6_visible_tree_ids)
        if picked is not None:
            args.task6_person_id = picked

    cases = [
        ("task2_sql_recursive_single_gen", lambda: run_sql_task2(args.task2_person_id, args.max_depth)),
        ("task2_sql_dominant_mixed", lambda: query_task_2_ancestors(args.task2_person_id, args.max_depth)),
        (
            "task6_sql_recursive_single_gen",
            lambda: run_sql_task6(args.task6_person_id, args.max_depth, task6_visible_tree_ids),
        ),
        (
            "task6_python_assisted_single_gen",
            lambda: query_task_6_descendants(args.task6_person_id, args.max_depth, set(task6_visible_tree_ids)),
        ),
    ]

    all_runs = []
    for case_name, fn in cases:
        all_runs.extend(benchmark_case(case_name, fn, args.warmup, args.repeats))

    summary = summarize_runs(all_runs)

    raw_csv = outdir / "raw_runs.csv"
    summary_csv = outdir / "summary.csv"
    summary_md = outdir / "summary.md"
    explain_t2 = outdir / "explain_task2_sql_recursive.txt"
    explain_t6 = outdir / "explain_task6_sql_recursive.txt"

    write_raw_csv(raw_csv, all_runs)
    write_summary_csv(summary_csv, summary)
    write_summary_md(summary_md, args, summary, task6_visible_tree_ids)

    save_explain(explain_t2, TASK2_SQL_RECURSIVE, (args.task2_person_id, args.max_depth, args.max_depth))
    save_explain(
        explain_t6,
        TASK6_SQL_RECURSIVE,
        (
            args.task6_person_id,
            args.task6_person_id,
            list(task6_visible_tree_ids),
            list(task6_visible_tree_ids),
            args.max_depth,
            args.max_depth,
        ),
    )

    print(f"Benchmark artifacts written to: {outdir}")
    print(f"- task6_person_id_used: {args.task6_person_id}")
    print(f"- {raw_csv.name}")
    print(f"- {summary_csv.name}")
    print(f"- {summary_md.name}")
    print(f"- {explain_t2.name}")
    print(f"- {explain_t6.name}")


if __name__ == "__main__":
    main()
