if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$USER'" | grep -q 1; then
	echo "Role '$USER' already exists. Skipping createuser."
else
	sudo -u postgres createuser "$USER"
fi
sudo -u postgres createdb fgdb 2>/dev/null || true
sudo -u postgres psql -d fgdb -f ./init/FG.sql
sudo -u postgres psql -d fgdb -c "\dt"
export DB_USER=$USER
export DB_PASSWORD=
export DB_HOST=/var/run/postgresql
export DB_NAME=fgdb
load_csv_value="${LOAD_CSV:-true}"
load_csv_normalized="$(printf '%s' "$load_csv_value" | tr '[:upper:]' '[:lower:]')"

if [ "$load_csv_normalized" = "false" ] || [ "$load_csv_normalized" = "0" ] || [ "$load_csv_normalized" = "no" ]; then
	echo "LOAD_CSV=$load_csv_value, skip CSV loading."
else
	echo "LOAD_CSV=$load_csv_value, loading CSV data..."
	python3 ./application/load_csv.py
fi
python3 ./application/app.py
