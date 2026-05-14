import argparse
import csv
import math
import random
from collections import defaultdict
from datetime import date
from pathlib import Path


SURNAMES = ["赵", "钱", "孙", "李", "周", "武", "郑", "王", "冯", "陈"]

# 每个家谱可用 30 代字（第二个字）
GENERATION_CHARS = {
    "赵": list("德世承宗永文昌启瑞光仁义礼信景运开宏业忠良继远声孝友传家兴盛"),
    "钱": list("景运开宏业忠良继远声孝友传家绍祖延嘉庆诗书振彩堂仁德兴邦兴盛"),
    "孙": list("绍祖延嘉庆诗书振彩堂仁德兴邦明德昭先绪清风继世长福禄安康兴盛"),
    "李": list("明德昭先绪清风继世长福禄安康克绍敦伦纪家声庆有余贤良忠厚兴盛"),
    "周": list("克绍敦伦纪家声庆有余贤良忠厚承先光祖业英杰振华邦礼智信诚兴盛"),
    "武": list("承先光祖业英杰振华邦礼智信诚修齐传孝友仁义启鸿图诗书继盛兴盛"),
    "郑": list("修齐传孝友仁义启鸿图诗书继盛国正天心顺家和万代兴礼乐安宁兴盛"),
    "王": list("国正天心顺家和万代兴礼乐安宁弘道崇文德安邦定世基忠孝永昌兴盛"),
    "冯": list("弘道崇文德安邦定世基忠孝永昌继志敦仁厚诗礼振家声祥瑞长春兴盛"),
    "陈": list("继志敦仁厚诗礼振家声祥瑞长春德世承宗永文昌启瑞光仁义礼信兴盛"),
}

# 名字第三个字随机库
NAME_POOL = list("安明华文远宁泽林修然博轩宇辰涛凯嘉瑞颖彤静雪婷磊航昊楠妍璇")

ANCESTOR_START_YEAR = 1200
BASE_YEAR = 2026
GENERATION_SPAN_YEARS = 25
BIRTH_YEAR_JITTER = 4
MIN_LIFESPAN = 50
MAX_LIFESPAN = 100
TARGET_PER_TREE = 50000
LOW_COMPLEXITY_TARGET_PER_TREE = 2000
MIN_CHILDREN_PER_FATHER = 1
GENERATION_WEIGHT_POWER = 2


def build_people_and_relationships(
    seed: int,
    min_gen: int,
    max_gen: int,
    ancestor_year: int,
    target_per_tree: int,
):
    rng = random.Random(seed)
    today = date.today().isoformat()

    users = []

    trees = []
    people = []
    rel_set = set()
    spouse_of = {}

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
        gen_count = 30
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

    all_tree_mask = (1 << len(trees)) - 1
    users = [
        {
            "user_id": 1,
            "username": "admin",
            "password_hash": "$2b$12$demo.admin.hash",
            "email": "admin@fg.local",
            "is_admin": "true",
            "tree_access_mask": all_tree_mask,
        }
    ]

    # 前五个高复杂族谱（每族 5w），后五个低复杂族谱（每族尽量少）
    high_complexity_tree_ids = {1, 2, 3, 4, 5}
    low_complexity_tree_ids = {6, 7, 8, 9, 10}
    target_by_tree = {
        tree_id: (target_per_tree if tree_id in high_complexity_tree_ids else LOW_COMPLEXITY_TARGET_PER_TREE)
        for tree_id in range(1, len(SURNAMES) + 1)
    }

    # 通婚仅允许在各自分组内部进行
    marriage_pool_by_tree = {}
    for tree_id in range(1, len(SURNAMES) + 1):
        if tree_id in high_complexity_tree_ids:
            marriage_pool_by_tree[tree_id] = sorted(high_complexity_tree_ids - {tree_id})
        else:
            marriage_pool_by_tree[tree_id] = sorted(low_complexity_tree_ids - {tree_id})

    male_by_tree_gen = defaultdict(list)
    female_by_tree_gen = defaultdict(list)
    count_by_tree = defaultdict(int)

    def add_person(tree_id, surname, gen_index, gender, birth_year):
        if birth_year > BASE_YEAR:
            return None
        pid = next_person_id()
        gen_char = GENERATION_CHARS[surname][gen_index - 1]
        last_char = rng.choice(NAME_POOL)
        name = f"{surname}{gen_char}{last_char}"
        lifespan = rng.randint(MIN_LIFESPAN, MAX_LIFESPAN)
        death_year = birth_year + lifespan
        death_date = "" if death_year > BASE_YEAR else f"{death_year}-01-01"
        people.append(
            {
                "person_id": pid,
                "tree_id": tree_id,
                "name": name,
                "gender": gender,
                "birth_date": f"{birth_year}-01-01",
                "death_date": death_date,
                "generation": gen_index,
                "surname": surname,
            }
        )
        count_by_tree[tree_id] += 1
        if gender == "male":
            male_by_tree_gen[(tree_id, gen_index)].append(pid)
        else:
            female_by_tree_gen[(tree_id, gen_index)].append(pid)
        return pid

    # 第一代：每树 1 男 1 女（基础成员）
    for tree in trees:
        tid = tree["tree_id"]
        surname = tree["surname"]
        base_year = ancestor_year + rng.randint(0, 20)
        add_person(tid, surname, 1, "male", base_year)
        add_person(tid, surname, 1, "female", base_year + 2)

    # 从第二代开始迭代扩展
    for gen_index in range(2, 31):
        for tree in trees:
            tid = tree["tree_id"]
            surname = tree["surname"]
            if gen_index > generations_by_tree[tid]:
                continue

            base_year = ancestor_year + (gen_index - 1) * GENERATION_SPAN_YEARS
            max_offset = min(BIRTH_YEAR_JITTER, BASE_YEAR - base_year)
            if max_offset < 0:
                generations_by_tree[tid] = min(generations_by_tree[tid], gen_index - 1)
                continue
            born_base = base_year + rng.randint(0, max_offset)

            fathers = male_by_tree_gen.get((tid, gen_index - 1), [])
            if not fathers:
                continue

            remaining_generations = generations_by_tree[tid] - gen_index + 1
            remaining_needed = max(0, target_by_tree[tid] - count_by_tree[tid])
            if remaining_needed <= 0:
                generation_quota = 0
            else:
                # Distribute remaining target with increasing weights (later generations get more).
                if GENERATION_WEIGHT_POWER == 2:
                    weight_sum = (
                        remaining_generations
                        * (remaining_generations + 1)
                        * (2 * remaining_generations + 1)
                    ) // 6
                else:
                    weight_sum = (remaining_generations * (remaining_generations + 1)) // 2
                generation_quota = math.ceil(remaining_needed / max(1, weight_sum))
            min_children_total = max(
                len(fathers) * MIN_CHILDREN_PER_FATHER,
                generation_quota,
            )
            base_children = min_children_total // len(fathers)
            extra_children = min_children_total % len(fathers)

            for father_idx, father_pid in enumerate(fathers):
                candidate_wives = []
                for other_tid in marriage_pool_by_tree[tid]:
                    candidate_wives.extend(female_by_tree_gen.get((other_tid, gen_index - 1), []))

                wife_pid = spouse_of.get(father_pid)
                if wife_pid is None:
                    available_wives = [wid for wid in candidate_wives if wid not in spouse_of]
                    if available_wives:
                        # 防御性校验：婚配必须异性
                        opposite_gender_wives = [
                            wid for wid in available_wives if people[wid - 1]["gender"] == "female"
                        ]
                        if not opposite_gender_wives:
                            wife_pid = None
                        else:
                            wife_pid = rng.choice(opposite_gender_wives)
                    if wife_pid is not None:
                        spouse_pair = tuple(sorted((father_pid, wife_pid)))
                        rel_set.add((spouse_pair[0], spouse_pair[1], "spouse"))
                        spouse_of[father_pid] = wife_pid
                        spouse_of[wife_pid] = father_pid

                # 按剩余目标人数分配子女，保证族谱规模下限
                child_count = base_children + (1 if father_idx < extra_children else 0)
                if child_count < MIN_CHILDREN_PER_FATHER:
                    child_count = MIN_CHILDREN_PER_FATHER
                male_count = 0
                for _ in range(child_count):
                    gender = "male" if rng.random() < 0.52 else "female"
                    child_birth = born_base + rng.randint(0, min(BIRTH_YEAR_JITTER, BASE_YEAR - born_base))
                    child_pid = add_person(tid, surname, gen_index, gender, child_birth)
                    if child_pid is None:
                        continue
                    if gender == "male":
                        male_count += 1
                    rel_set.add((father_pid, child_pid, "parent"))
                    if wife_pid is not None:
                        rel_set.add((wife_pid, child_pid, "parent"))

                # 至少保证一个男性后代，降低父系断代概率
                if male_count == 0:
                    child_birth = born_base + rng.randint(0, min(BIRTH_YEAR_JITTER, BASE_YEAR - born_base))
                    child_pid = add_person(tid, surname, gen_index, "male", child_birth)
                    if child_pid is not None:
                        rel_set.add((father_pid, child_pid, "parent"))
                        if wife_pid is not None:
                            rel_set.add((wife_pid, child_pid, "parent"))

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
                "generation": p["generation"],
                "death_date": p["death_date"],
            }
        )

    relationships = [
        {"person1_id": p1, "person2_id": p2, "rel_type": rel_type}
        for p1, p2, rel_type in sorted(rel_set)
    ]
    return users, trees, clean_people, relationships


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
        default=30,
        help="Minimum generations per tree (2-30).",
    )
    parser.add_argument(
        "--max-gen",
        type=int,
        default=30,
        help="Maximum generations per tree (2-30).",
    )
    parser.add_argument(
        "--target-per-tree",
        type=int,
        default=TARGET_PER_TREE,
        help="Minimum number of people per family tree.",
    )
    parser.add_argument(
        "--ancestor-year",
        type=int,
        default=ANCESTOR_START_YEAR,
        help="Base birth year for the first generation.",
    )
    parser.add_argument(
        "--gen",
        type=int,
        default=None,
        help="Fixed generations per tree (2-30). If set, min/max are ignored.",
    )
    args = parser.parse_args()

    if args.gen is not None:
        if not (2 <= args.gen <= 30):
            raise ValueError("--gen must be in [2, 30].")
        min_gen = args.gen
        max_gen = args.gen
    else:
        if not (2 <= args.min_gen <= 30 and 2 <= args.max_gen <= 30):
            raise ValueError("--min-gen and --max-gen must be in [2, 30].")
        if args.min_gen > args.max_gen:
            raise ValueError("--min-gen must be <= --max-gen.")
        min_gen = args.min_gen
        max_gen = args.max_gen

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    users, trees, people, relationships = build_people_and_relationships(
        args.seed,
        min_gen,
        max_gen,
        args.ancestor_year,
        args.target_per_tree,
    )

    write_csv(
        out_dir / "user.csv",
        ["user_id", "username", "password_hash", "email", "is_admin", "tree_access_mask"],
        users,
    )
    write_csv(
        out_dir / "family_tree.csv",
        ["tree_id", "name", "surname", "revision_date", "creator_id"],
        trees,
    )
    write_csv(
        out_dir / "person.csv",
        ["person_id", "tree_id", "name", "gender", "birth_date", "generation", "death_date"],
        people,
    )
    write_csv(
        out_dir / "relationship.csv",
        ["person1_id", "person2_id", "rel_type"],
        relationships,
    )
    print(f"Generated CSV files in: {out_dir}")
    print(f"Trees: {len(trees)}")
    print(f"People: {len(people)}")
    print(f"Relationships: {len(relationships)}")


if __name__ == "__main__":
    main()
