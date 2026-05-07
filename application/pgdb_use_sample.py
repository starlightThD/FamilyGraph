import os

import psycopg2


TABLES = [
	"User",
	"Person",
	"FamilyTree",
	"Relationship",
	"KinshipClosure",
]


def get_connection():
	return psycopg2.connect(
		host=os.getenv("DB_HOST", "localhost"),
		port=os.getenv("DB_PORT", "5432"),
		dbname=os.getenv("DB_NAME", "fgdb"),
		user=os.getenv("DB_USER", "postgres"),
		password=os.getenv("DB_PASSWORD", "postgres"),
	)


def table_count(cursor, table_name):
	cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
	return cursor.fetchone()[0]


def table_preview(cursor, table_name, limit=5):
	cursor.execute(f'SELECT * FROM "{table_name}" LIMIT %s', (limit,))
	columns = [desc[0] for desc in cursor.description]
	rows = cursor.fetchall()
	return columns, rows


def main():
	with get_connection() as conn:
		with conn.cursor() as cursor:
			for table_name in TABLES:
				count = table_count(cursor, table_name)
				columns, rows = table_preview(cursor, table_name)
				print(f"\n== {table_name} (rows: {count}) ==")
				print(", ".join(columns))
				for row in rows:
					print(row)


if __name__ == "__main__":
	main()
