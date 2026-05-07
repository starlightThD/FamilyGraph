if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$USER'" | grep -q 1; then
	echo "Role '$USER' already exists. Skipping createuser."
else
	sudo -u postgres createuser "$USER"
fi
sudo -u postgres createdb fgdb
sudo -u postgres psql -d fgdb -f ./init/FG.sql
sudo -u postgres psql -d fgdb -c "\dt"
export DB_USER=$USER
export DB_PASSWORD=
export DB_HOST=/var/run/postgresql
export DB_NAME=fgdb
python3 ./backend/main.py