import os
from pathlib import Path

import psycopg2


TABLE_LOADS = [
    ("User", "user.csv"),
    ("FamilyTree", "family_tree.csv"),
    ("Person", "person.csv"),
    ("Relationship", "relationship.csv"),
    ("KinshipClosure", "kinship_closure.csv"),
]


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fgdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


def load_table(cursor, table_name, csv_path):
    with csv_path.open("r", encoding="utf-8") as handle:
        cursor.copy_expert(
            f'COPY "{table_name}" FROM STDIN WITH (FORMAT csv, HEADER true)',
            handle,
        )


def main():
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"

    with get_connection() as conn:
        with conn.cursor() as cursor:
            for table_name, file_name in TABLE_LOADS:
                csv_path = data_dir / file_name
                if not csv_path.exists():
                    raise FileNotFoundError(f"Missing CSV: {csv_path}")
                load_table(cursor, table_name, csv_path)
                conn.commit()
                print(f"Loaded {table_name} from {file_name}")


if __name__ == "__main__":
    main()
