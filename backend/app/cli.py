"""Administrative commands.

    python -m app.cli bootstrap --email ... --password ...
    python -m app.cli seed

Schema changes are not done here. `alembic upgrade head` is the only thing that creates or
alters tables, so there is one path to a database and one place to look at its history.
"""

import argparse
import sys

from sqlalchemy import inspect, select

from app.database.database import SessionLocal, engine
from app.database.models import Role, User
from app.database.seed import seed_reference_data
from app.security import authentication as auth

MINIMUM_PASSWORD_LENGTH = 12


def _require_schema() -> None:
    if not inspect(engine).has_table("users"):
        sys.exit("The schema is missing. Run 'alembic upgrade head' first.")


def seed(_: argparse.Namespace) -> None:
    _require_schema()
    with SessionLocal() as db:
        counts = seed_reference_data(db)
    for table, count in counts.items():
        print(f"  {table:22} {count}")
    print(f"reference data present: {sum(counts.values())} rows")


def bootstrap(arguments: argparse.Namespace) -> None:
    _require_schema()
    if len(arguments.password) < MINIMUM_PASSWORD_LENGTH:
        sys.exit(f"The password must be at least {MINIMUM_PASSWORD_LENGTH} characters.")

    email = arguments.email.lower().strip()
    with SessionLocal() as db:
        seed_reference_data(db)
        if db.scalar(select(User).where(User.email == email)):
            sys.exit(f"{email} already has an account.")
        db.add(
            User(
                email=email,
                password_hash=auth.hash_password(arguments.password),
                display_name=arguments.name,
                role=Role.ADMIN if arguments.admin else Role.DOCTOR,
                speciality=arguments.speciality,
                registration_number=arguments.registration,
            )
        )
        db.commit()
    role = "administrator" if arguments.admin else "doctor"
    print(f"created {role} account for {email}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Pain Score administration.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("seed", help="load the reference taxonomies").set_defaults(handler=seed)

    create = commands.add_parser("bootstrap", help="create the first account")
    create.add_argument("--email", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--name", default="Administrator")
    create.add_argument("--speciality", default=None)
    create.add_argument("--registration", default=None)
    create.add_argument("--admin", action="store_true", default=True)
    create.add_argument("--doctor", dest="admin", action="store_false")
    create.set_defaults(handler=bootstrap)

    arguments = parser.parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
