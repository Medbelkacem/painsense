import argparse
import sys

from sqlalchemy import inspect, select

from database.models import Role, User
from database.seed import seed_reference_data
from database.session import SessionLocal, engine
from security import authentication as auth

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
                role=Role.SUPER_ADMIN if arguments.admin else Role.DOCTOR,
                speciality=arguments.speciality,
                registration_number=arguments.registration,
            )
        )
        db.commit()
    role = "administrator" if arguments.admin else "doctor"
    print(f"created {role} account for {email}")


def train(arguments: argparse.Namespace) -> None:
    """Fit the pain model on the newest generated dataset and make it the active one.

    An empty database has no registered model, and the estimator refuses rather than
    guesses until one exists. Generate a dataset with scripts/generate_dataset.py first.
    """
    from pathlib import Path as _Path

    from backend.ai import training

    _require_schema()
    try:
        with SessionLocal() as db:
            row = training.train(
                db,
                dataset_path=_Path(arguments.dataset) if arguments.dataset else None,
                seed=arguments.seed,
                cv_folds=arguments.cv_folds,
            )
    except training.NoDataset as exc:
        sys.exit(f"Model not trained: {exc}")
    print(f"registered and activated {row.version}: MAE {row.mae}, n_test {row.n_test}")


def sync(arguments: argparse.Namespace) -> None:
    """Run a dataset synchronisation in the foreground.

    The worker normally does this on a schedule. Running it here is for a first pass on a
    new deployment and for seeing a publisher's response while configuring one, so the
    output is the per-source summary rather than a job id.
    """
    import json

    _require_schema()
    from backend.sync import service

    with SessionLocal() as db:
        service.ensure_sources(db)
        if arguments.source:
            summaries = [
                service.run_source(
                    db,
                    arguments.source,
                    trigger="cli",
                    acquire=not arguments.discover_only,
                    limit=arguments.limit,
                ).as_dict()
            ]
        else:
            summaries = service.run_due(db, trigger="cli")
    print(json.dumps(summaries, indent=2))


def train_burn_tbsa(arguments: argparse.Namespace) -> None:
    """Fit the burn surface-area research model and record it in the model registry.

    Needs the MassHumanBurns dataset extracted at `--dataset`. That dataset is Apache-2.0
    and can be retrieved through the external dataset synchronisation, but its imagery
    archives are far larger than the default per-dataset size cap, so in practice the
    archives are fetched and extracted by hand and this command is pointed at the result.
    """
    import json

    _require_schema()
    from pathlib import Path as _Path

    from backend.burns import tbsa_model

    root = _Path(arguments.dataset)
    try:
        samples, meta = tbsa_model.load(root, limit_subjects=arguments.subjects)
    except tbsa_model.DatasetUnavailable as exc:
        print(f"Model not trained: {exc}")
        raise SystemExit(2) from exc

    result, model = tbsa_model.train(
        samples, seed=arguments.seed, cv_folds=arguments.cv_folds
    )
    report = {"dataset": meta, "result": result.as_dict()}
    if arguments.register:
        with SessionLocal() as db:
            report["model_version"] = tbsa_model.persist_and_register(db, result, model, meta)
    else:
        report["model_version"] = None
        report["note"] = "not registered; pass --register to record it in the model registry"
    print(json.dumps(report, indent=2))


def train_signal_pain(arguments: argparse.Namespace) -> None:
    """Fit the signal pain model on the PainMonit database and register it.

    Needs the database at `--dataset`, either as the two archives it is downloaded as or
    extracted. It is obtained under a signed usage agreement that forbids redistribution,
    so it is never held in this repository and this command is pointed at wherever a copy
    was legitimately put. Nothing is copied out of it: the archives are read in place and
    only the fitted model and its scores are kept.
    """
    import json
    from pathlib import Path as _Path

    _require_schema()
    from backend.signals import painmonit
    from backend.signals import training as signal_training

    try:
        with SessionLocal() as db:
            row, scored = signal_training.train(
                db,
                dataset=_Path(arguments.dataset),
                half=arguments.half,
                seed=arguments.seed,
                folds=arguments.cv_folds or signal_training.FOLDS,
                limit_subjects=arguments.subjects,
                activate=arguments.activate,
            )
            report = {
                "model_version": row.version,
                "active": row.is_active,
                "scale": painmonit.SCALES[arguments.half],
                # Picked the same way the trainer picks it, rather than matched back by
                # score, which two candidates can tie on.
                "selected": min(scored, key=lambda result: result.mae).as_dict(),
                "candidates": [result.as_dict() for result in scored],
                "notes": row.notes,
            }
    except painmonit.NoCorpus as exc:
        print(f"Model not trained: {exc}")
        raise SystemExit(2) from exc
    print(json.dumps(report, indent=2))


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

    fit = commands.add_parser("train", help="fit and activate the pain model")
    fit.add_argument("--dataset", default=None, help="a generated dataset; default: the newest")
    fit.add_argument("--seed", type=int, default=0)
    fit.add_argument("--cv-folds", type=int, default=5)
    fit.set_defaults(handler=train)

    run = commands.add_parser(
        "sync", help="synchronise external dataset publishers now"
    )
    run.add_argument("--source", default=None, help="one source code; default is every due source")
    run.add_argument(
        "--discover-only",
        action="store_true",
        help="catalogue what the publisher lists without downloading anything",
    )
    run.add_argument("--limit", type=int, default=None, help="cap acquisitions for this run")
    run.set_defaults(handler=sync)

    burn = commands.add_parser(
        "train-burn-tbsa",
        help="fit the burn surface-area research model from an extracted dataset",
    )
    burn.add_argument("--dataset", required=True, help="directory holding the extracted dataset")
    burn.add_argument("--subjects", type=int, default=None, help="cap subjects, for a quick run")
    burn.add_argument("--seed", type=int, default=42)
    burn.add_argument("--cv-folds", type=int, default=3)
    burn.add_argument(
        "--register",
        action="store_true",
        help="record the fitted model in the model registry, inactive",
    )
    burn.set_defaults(handler=train_burn_tbsa)

    signal = commands.add_parser(
        "train-signal-pain",
        help="fit the signal pain model from the PainMonit database",
    )
    signal.add_argument(
        "--dataset",
        required=True,
        help="directory holding PMED.zip and PMCD.zip, or their extracted trees",
    )
    # Spelled out rather than read from app.signals.painmonit, so that building the parser
    # does not import pandas and scikit-learn for every other subcommand. The handler
    # passes the value through and the reader refuses anything it does not know.
    signal.add_argument(
        "--half",
        choices=("experimental", "clinical"),
        default="experimental",
        help="which half of the database to fit (default: %(default)s)",
    )
    signal.add_argument("--subjects", type=int, default=None, help="cap people, for a quick run")
    signal.add_argument("--seed", type=int, default=0)
    signal.add_argument(
        "--cv-folds", type=int, default=None, help="person-grouped folds (default: 5)"
    )
    signal.add_argument(
        "--no-activate",
        dest="activate",
        action="store_false",
        help="register the model without making it the active signal model",
    )
    signal.set_defaults(handler=train_signal_pain)

    arguments = parser.parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
