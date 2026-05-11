import argparse
import csv
import random
from collections import defaultdict, deque
from datetime import date
from pathlib import Path


SURNAMES = ["赵", "钱", "孙", "李", "周", "武", "郑", "王", "冯", "陈"]

# 每个家谱可用 14 代字（第二个字）
GENERATION_CHARS = {
    "赵": list("德世承宗永文昌启瑞光仁义礼信"),
    "钱": list("景运开宏业忠良继远声孝友传家"),
    "孙": list("绍祖延嘉庆诗书振彩堂仁德兴邦"),
    "李": list("明德昭先绪清风继世长福禄安康"),
    "周": list("克绍敦伦纪家声庆有余贤良忠厚"),
    "武": list("承先光祖业英杰振华邦礼智信诚"),
    "郑": list("修齐传孝友仁义启鸿图诗书继盛"),
    "王": list("国正天心顺家和万代兴礼乐安宁"),
    "冯": list("弘道崇文德安邦定世基忠孝永昌"),
    "陈": list("继志敦仁厚诗礼振家声祥瑞长春"),
}

# 名字第三个字随机库
NAME_POOL = list("安明华文远宁泽林修然博轩宇辰涛凯嘉瑞颖彤静雪婷磊航昊楠妍璇")


def build_people_and_relationships(seed: int, min_gen: int, max_gen: int):
    rng = random.Random(seed)
    today = date.today().isoformat()

    users = [
        {
            "user_id": 1,
            "username": "admin",
            "password_hash": "$2b$12$demo.admin.hash",
            "email": "admin@familygraph.local",
            "is_admin": "true",
        }
    ]

    trees = []
    people = []
    rel_set = set()

    person_id = 1
    surname_to_tree = {}
    generations_by_tree = {}

    def next_person_id():
        nonlocal person_id
        pid = person_id
        person_id += 1
        return pid

    for idx, surname in enumerate(SURNAMES, start=1):
        surname_to_tree[surname] = idx
        gen_count = rng.randint(min_gen, max_gen)
        generations_by_tree[idx] = gen_count
        trees.append(
            {
                "tree_id": idx,
                "name": f"{surname}氏族谱",
                "surname": surname,
                "revision_date": today,
                "creator_id": 1,
            }
        )

    male_by_tree_gen = defaultdict(list)
    female_by_tree_gen = defaultdict(list)

    def add_person(tree_id, surname, gen_index, gender, birth_year):
        pid = next_person_id()
        gen_char = GENERATION_CHARS[surname][gen_index - 1]
        last_char = rng.choice(NAME_POOL)
        name = f"{surname}{gen_char}{last_char}"
        people.append(
            {
                "person_id": pid,
                "tree_id": tree_id,
                "name": name,
                "gender": gender,
                "birth_date": f"{birth_year}-01-01",
                "death_date": "",
                "generation": gen_index,
                "surname": surname,
            }
        )
        if gender == "male":
            male_by_tree_gen[(tree_id, gen_index)].append(pid)
        else:
            female_by_tree_gen[(tree_id, gen_index)].append(pid)
        return pid

    # 第一代：每树 1 男 1 女（基础成员）
    for tree in trees:
        tid = tree["tree_id"]
        surname = tree["surname"]
        base_year = 1860 + rng.randint(0, 20)
        add_person(tid, surname, 1, "male", base_year)
        add_person(tid, surname, 1, "female", base_year + 2)

    # 从第二代开始迭代扩展
    for gen_index in range(2, 15):
        for tree in trees:
            tid = tree["tree_id"]
            surname = tree["surname"]
            if gen_index > generations_by_tree[tid]:
                continue

            fathers = male_by_tree_gen.get((tid, gen_index - 1), [])
            if not fathers:
                continue

            for father_pid in fathers:
                candidate_wives = []
                for other_tid in surname_to_tree.values():
                    if other_tid == tid:
                        continue
                    candidate_wives.extend(female_by_tree_gen.get((other_tid, gen_index - 1), []))

                wife_pid = None
                if candidate_wives:
                    wife_pid = rng.choice(candidate_wives)
                    spouse_pair = tuple(sorted((father_pid, wife_pid)))
                    rel_set.add((spouse_pair[0], spouse_pair[1], "spouse"))

                # 每个父系家庭生成 3~6 个子女，归入父亲家谱并同姓
                child_count = rng.randint(3, 6)
                born_base = 1860 + (gen_index - 1) * 25 + rng.randint(0, 5)
                male_count = 0
                for _ in range(child_count):
                    gender = "male" if rng.random() < 0.52 else "female"
                    child_pid = add_person(tid, surname, gen_index, gender, born_base + rng.randint(0, 4))
                    if gender == "male":
                        male_count += 1
                    rel_set.add((father_pid, child_pid, "parent"))
                    if wife_pid is not None:
                        rel_set.add((wife_pid, child_pid, "parent"))

                # 至少保证一个男性后代，降低父系断代概率
                if male_count == 0:
                    child_pid = add_person(tid, surname, gen_index, "male", born_base + rng.randint(0, 4))
                    rel_set.add((father_pid, child_pid, "parent"))
                    if wife_pid is not None:
                        rel_set.add((wife_pid, child_pid, "parent"))

    # 计算祖先闭包
    child_map = defaultdict(list)
    for p1, p2, rel_type in rel_set:
        if rel_type == "parent":
            child_map[p1].append(p2)

    closure = set()
    for ancestor in child_map.keys():
        queue = deque((child, 1) for child in child_map[ancestor])
        seen = set()
        while queue:
            desc, depth = queue.popleft()
            if desc in seen:
                continue
            seen.add(desc)
            closure.add((ancestor, desc, depth))
            for nxt in child_map.get(desc, []):
                queue.append((nxt, depth + 1))

    # 清理内部字段
    clean_people = []
    for p in people:
        clean_people.append(
            {
                "person_id": p["person_id"],
                "tree_id": p["tree_id"],
                "name": p["name"],
                "gender": p["gender"],
                "birth_date": p["birth_date"],
                "death_date": p["death_date"],
            }
        )

    relationships = [
        {"person1_id": p1, "person2_id": p2, "rel_type": rel_type}
        for p1, p2, rel_type in sorted(rel_set)
    ]
    closures = [
        {"ancestor_id": a, "descendant_id": d, "depth": depth}
        for a, d, depth in sorted(closure)
    ]

    return users, trees, clean_people, relationships, closures


def write_csv(path: Path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Generate FamilyGraph CSV seed data.")
    parser.add_argument("--seed", type=int, default=20260511, help="Random seed for reproducible output.")
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(Path(__file__).resolve().parent),
        help="Output directory for CSV files.",
    )
    parser.add_argument(
        "--min-gen",
        type=int,
        default=8,
        help="Minimum generations per tree (2-14).",
    )
    parser.add_argument(
        "--max-gen",
        type=int,
        default=14,
        help="Maximum generations per tree (2-14).",
    )
    parser.add_argument(
        "--gen",
        type=int,
        default=None,
        help="Fixed generations per tree (2-14). If set, min/max are ignored.",
    )
    args = parser.parse_args()

    if args.gen is not None:
        if not (2 <= args.gen <= 14):
            raise ValueError("--gen must be in [2, 14].")
        min_gen = args.gen
        max_gen = args.gen
    else:
        if not (2 <= args.min_gen <= 14 and 2 <= args.max_gen <= 14):
            raise ValueError("--min-gen and --max-gen must be in [2, 14].")
        if args.min_gen > args.max_gen:
            raise ValueError("--min-gen must be <= --max-gen.")
        min_gen = args.min_gen
        max_gen = args.max_gen

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    users, trees, people, relationships, closures = build_people_and_relationships(
        args.seed, min_gen, max_gen
    )

    write_csv(
        out_dir / "user.csv",
        ["user_id", "username", "password_hash", "email", "is_admin"],
        users,
    )
    write_csv(
        out_dir / "family_tree.csv",
        ["tree_id", "name", "surname", "revision_date", "creator_id"],
        trees,
    )
    write_csv(
        out_dir / "person.csv",
        ["person_id", "tree_id", "name", "gender", "birth_date", "death_date"],
        people,
    )
    write_csv(
        out_dir / "relationship.csv",
        ["person1_id", "person2_id", "rel_type"],
        relationships,
    )
    write_csv(
        out_dir / "kinship_closure.csv",
        ["ancestor_id", "descendant_id", "depth"],
        closures,
    )

    print(f"Generated CSV files in: {out_dir}")
    print(f"Trees: {len(trees)}")
    print(f"People: {len(people)}")
    print(f"Relationships: {len(relationships)}")
    print(f"KinshipClosure rows: {len(closures)}")


if __name__ == "__main__":
    main()
