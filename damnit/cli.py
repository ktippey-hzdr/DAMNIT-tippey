import inspect
import json
import logging
import sys
import textwrap
import traceback
from argparse import ArgumentParser
from pathlib import Path

try:
    from termcolor import colored
except ModuleNotFoundError:
    def colored(text, color=None, **kwargs):
        """Return uncoloured CLI text when termcolor is unavailable."""
        return str(text)

from .site_config import (
    find_proposal_dir,
    load_site_config,
    write_site_config_template,
)


def find_proposal(propno):
    """Compatibility wrapper used by tests and old call sites."""
    return find_proposal_dir(propno, base_dir=Path.cwd())


def _default_db_subdir(base_dir: Path | None = None) -> Path:
    cfg = load_site_config(base_dir or Path.cwd())
    rel = cfg.get("lab", {}).get("damnit_directory_name", "usr/Shared/amore")
    return Path(rel)


def excepthook(exc_type, value, tb):
    """
    Hook to start an IPython shell when an unhandled exception is caught.
    """
    tb_msg = "".join(traceback.format_exception(exc_type, value, tb))
    traceback.print_exception(exc_type, value, tb)
    print()

    # Find the deepest frame in the stack that comes from us. We don't want to
    # go straight to the last frame because that may be in some other library.
    module_path = Path(__file__).parent.parent
    target_frame = None
    target_file = None
    for frame, lineno in traceback.walk_tb(tb):
        frame_file = Path(inspect.getframeinfo(frame).filename)
        if module_path in frame_file.parents:
            target_frame = frame
            target_file = frame_file.relative_to(module_path)

    # Start an IPython REPL
    header = f"""
    Tip: call {colored('__tb()', 'red')} to print the traceback again.
    Dropped into {colored(target_file, 'green')} at line {colored(target_frame.f_lineno, 'green')}.
    """
    print(textwrap.dedent(header))

    import IPython
    IPython.start_ipython(argv=[], display_banner=False,
                          user_ns=target_frame.f_locals | target_frame.f_globals | {"__tb": lambda: print(tb_msg)})

def handle_config_args(args, kv, converters={}):
    key = args.key
    if key:
        key = key.replace('-', '_')
    if args.value and key in converters:
        args.value = converters[key](args.value)

    if args.delete:
        if not key:
            sys.exit("Error: no key specified to delete")
        del kv[key]
    elif key and (args.value is not None):
        if args.num:
            try:
                value = int(args.value)
            except ValueError:
                value = float(args.value)
        else:
            value = args.value
        kv[key] = value
    elif key:
        try:
            print(repr(kv[key]))
        except KeyError:
            sys.exit(f"Error: key {key} not found")
    else:
        for k, v in kv.items():
            print(f"{k}={v!r}")

def main(argv=None):
    # Check if script was called as amore-proto and show deprecation warning
    if Path(sys.argv[0]).name == 'amore-proto':
        print(colored("Warning: 'amore-proto' has been renamed to 'damnit'. Please update your scripts.", 'yellow'), file=sys.stderr)

    ap = ArgumentParser()
    ap.add_argument('--debug', action='store_true',
                    help="Show debug logs.")
    ap.add_argument('--debug-repl', action='store_true',
                    help="Drop into an IPython repl if an exception occurs. Local variables at the point of the exception will be available.")
    subparsers = ap.add_subparsers(required=True, dest='subcmd')

    gui_ap = subparsers.add_parser('gui', help="Launch application")
    gui_ap.add_argument(
        'proposal_or_dir', nargs='?',
        help="Either a proposal number or a database directory."
    )
    gui_ap.add_argument(
        '--no-kafka', action='store_true',
        help="Don't try connecting to XFEL's Kafka broker"
    )
    gui_ap.add_argument(
        "--software-opengl", action="store_true",
        help="Force software OpenGL. Use this if displaying interactive Plotly plots shows a black screen."
             "Active by default on Maxwell if not started on a display node."
    )

    listen_ap = subparsers.add_parser(
        'listen', help="Watch for new runs & extract data from them"
    )
    listen_args_grp = listen_ap.add_mutually_exclusive_group()
    listen_args_grp.add_argument(
        "listener_dir", type=Path, default=Path.cwd(), nargs="?",
        help="Path to the listener database directory"
    )
    listen_args_grp.add_argument(
        '--test', action='store_true',
        help="Manually enter 'migrated' runs for testing"
    )
    listen_args_grp.add_argument(
        '--daemonize', action='store_true',
        help="Start the listener under a separate process managed by supervisord."
    )

    listener_ap = subparsers.add_parser("listener", help="Manage the DAMNIT listener.")
    listener_subparser = listener_ap.add_subparsers(dest="listener_subcmd", required=True)

    listener_config_ap = listener_subparser.add_parser(
        "config", help="See or change the config for the DAMNIT listener"
    )
    listener_config_ap.add_argument(
        '-d', '--delete', action='store_true',
        help="Delete the specified key",
    )
    listener_config_ap.add_argument(
        '--num', action='store_true',
        help="Set the given value as a number instead of a string"
    )
    listener_config_ap.add_argument(
        'key', nargs='?',
        help="The config key to see/change. If not given, list the whole configuration"
    )
    listener_config_ap.add_argument(
        'value', nargs='?',
        help="A new value for the given key"
    )

    add_grp = listener_subparser.add_parser("add", help="Add a database to monitor")
    add_grp.add_argument(
        "proposal", type=int,
        help="Proposal number"
    )
    add_grp.add_argument(
        "db_dir", type=Path, nargs='?',
        help="Path to the database directory"
    )

    remove_grp = listener_subparser.add_parser("rm", help="Remove a database from being monitored")
    remove_grp.add_argument(
        "db_dir", type=Path,
        help="Path to the database directory to remove"
    )

    databases_grp = listener_subparser.add_parser(
        "databases",
        help="Display the DAMNIT databases currently being monitored"
    )

    combiner_ap = subparsers.add_parser("combiner", help="Manage the DAMNIT combiner.")
    combiner_subparser = combiner_ap.add_subparsers(dest="combiner_subcmd", required=True)
    combiner_start_grp = combiner_subparser.add_parser("run", help="Run the DAMNIT combiner")

    combiner_now_grp = combiner_subparser.add_parser("now",
         help="Combine files in the specified DAMNIT directory now. "
              "Can cause corruption if the combiner is running at the same time."
    )
    combiner_now_grp.add_argument("db_dir", type=Path)

    reprocess_ap = subparsers.add_parser(
        'reprocess',
        help="Extract data from specified runs. This does not send live updates yet."
    )
    reprocess_ap.add_argument(
        "--mock", action="store_true",
        help="Use a fake run object instead of loading one from disk."
             " Note: do not use the passed `run` object in your context file with this"
             " flag enabled, it will not contain any useful data."
    )
    reprocess_ap.add_argument(
        '--proposal', type=int,
        help="Proposal number, e.g. 1234"
    )
    reprocess_ap.add_argument(
        '--match', type=str, action="append", default=[],
        help="String to match against variable titles (case-insensitive). Not a regex, simply `str in var.title`."
    )
    reprocess_ap.add_argument(
        '--watch', action='store_true',
        help="Run jobs one-by-one with live output in the terminal"
    )
    reprocess_ap.add_argument(
        '--direct', action='store_true',
        help="Run processing in subprocesses on this node, instead of via Slurm"
    )
    reprocess_ap.add_argument(
        '--concurrent-jobs', type=int, default=-1,
        help="The maximum number of jobs that will run at once (default is the `concurrent_jobs` database setting)"
    )
    reprocess_ap.add_argument(
        'run', nargs='+',
        help="Run number, e.g. 96. Multiple runs can be specified at once, "
             "or pass 'all' to reprocess all runs in the database."
    )

    readctx_ap = subparsers.add_parser(
        'read-context',
        help="Re-read the context file and update variables in the database"
    )
    readctx_ap.add_argument(
        '--no-kafka', action='store_true',
        help="Don't try connecting to XFEL's Kafka broker"
    )

    proposal_ap = subparsers.add_parser(
        'proposal',
        help="Get or set the proposal number to collect metadata from"
    )
    proposal_ap.add_argument(
        'proposal', nargs='?', type=int,
        help="Proposal number to set, e.g. 1234"
    )

    new_id_ap = subparsers.add_parser(
        'new-id',
        help="Set a new (random) database ID. Useful if a copy has been made which should not share an ID with the original."
    )
    new_id_ap.add_argument(
        'db_dir', type=Path, default=Path.cwd(), nargs='?',
        help="Path to the database directory"
    )

    config_ap = subparsers.add_parser(
        'db-config',
        help="See or change config in this database"
    )
    config_ap.add_argument(
        '-d', '--delete', action='store_true',
        help="Delete the specified key",
    )
    config_ap.add_argument(
        '--num', action='store_true',
        help="Set the given value as a number instead of a string"
    )
    config_ap.add_argument(
        'key', nargs='?',
        help="The config key to see/change. If not given, list all config"
    )
    config_ap.add_argument(
        'value', nargs='?',
        help="A new value for the given key"
    )

    sample_data_ap = subparsers.add_parser(
        "sample-data",
        help="Generate synthetic runs for quick local testing",
    )
    sample_data_ap.add_argument(
        "db_dir", type=Path, nargs="?", default=Path.cwd(),
        help="DAMNIT database directory",
    )
    sample_data_ap.add_argument(
        "--proposal", type=int,
        help="Proposal number to use (defaults to database proposal)",
    )
    sample_data_ap.add_argument(
        "--runs", type=int, default=5,
        help="Number of synthetic runs to generate",
    )
    sample_data_ap.add_argument(
        "--start-run", type=int, default=1,
        help="First run number to generate",
    )
    sample_data_ap.add_argument(
        "--seed", type=int, default=7,
        help="Seed for deterministic synthetic data",
    )

    site_config_ap = subparsers.add_parser(
        "site-config",
        help="Show or create site-level DAMNIT configuration files",
    )
    site_config_subparsers = site_config_ap.add_subparsers(
        dest="site_config_subcmd", required=True
    )

    site_config_show_ap = site_config_subparsers.add_parser(
        "show", help="Print the effective site config as JSON"
    )
    site_config_show_ap.add_argument(
        "directory", type=Path, nargs="?", default=Path.cwd(),
        help="Directory to resolve site config from",
    )

    site_config_init_ap = site_config_subparsers.add_parser(
        "init", help="Write a site config template and .env example"
    )
    site_config_init_ap.add_argument(
        "--profile", choices=("hzdr", "xfel"), default="hzdr",
        help="Template profile to write",
    )
    site_config_init_ap.add_argument(
        "--force", action="store_true",
        help="Overwrite existing template files",
    )
    site_config_init_ap.add_argument(
        "directory", type=Path, nargs="?", default=Path.cwd(),
        help="Directory where files should be created",
    )

    migrate_ap = subparsers.add_parser(
        "migrate",
        help="Execute migrations to help upgrading. Do NOT execute a migration unless you know what you're doing."
    )
    migrate_ap.add_argument(
        "--dry-run", action="store_true"
    )
    migrate_subparsers = migrate_ap.add_subparsers(dest="migrate_subcmd")
    migrate_subparsers.add_parser(
        "v0-to-v1",
        help="Migrate the SQLite database and HDF5 files from v0 to v1."
    )
    migrate_subparsers.add_parser(
        "intermediate-v1",
        help="Migrate the SQLite database HDF5 files from an initial implementation of v1 to the final"
             " v1. Don't use this unless you know what you're doing."
    )

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)-8s %(name)-38s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    if args.debug_repl:
        sys.excepthook = excepthook

    if args.subcmd == 'gui':
        if args.proposal_or_dir is not None:
            if (path := Path(args.proposal_or_dir)).is_dir():
                context_dir = path
            elif args.proposal_or_dir.isdigit():
                proposal_root = Path(find_proposal(int(args.proposal_or_dir)))
                context_dir = proposal_root / _default_db_subdir(Path.cwd())
            else:
                sys.exit(f"{args.proposal_or_dir} is not a proposal number or DAMNIT database directory")
        else:
            context_dir = None

        from .gui.main_window import run_app
        return run_app(context_dir,
                       software_opengl=args.software_opengl,
                       connect_to_kafka=not args.no_kafka)

    elif args.subcmd == 'listen':
        from .backend import start_listener

        if args.daemonize:
            return start_listener(args.listener_dir)
        else:
            if args.test:
                from .backend.test_listener import listen
            else:
                from .backend.listener import listen

            return listen(args.listener_dir)

    elif args.subcmd == "listener":
        from .backend.listener import ListenerDB

        db = ListenerDB(Path.cwd())
        if args.listener_subcmd == "config":
            handle_config_args(args, db.settings,
                               # Convert `static_mode` to a bool
                               dict(static_mode=lambda x: bool(int(x))))
        elif args.listener_subcmd == "add":
            proposal_root = Path(find_proposal(args.proposal))
            official_dir = proposal_root / _default_db_subdir(Path.cwd())

            if args.db_dir is None:
                db_dir = official_dir
                official = True
            else:
                db_dir = args.db_dir
                official = db_dir == official_dir

            db.add_proposal_db(args.proposal, db_dir, official=official)
            print(f"Added proposal {args.proposal} at {db_dir}")
        elif args.listener_subcmd == "rm":
            db.remove_proposal_db(args.db_dir)
            print(f"Removed database at {args.db_dir}")
        elif args.listener_subcmd == "databases":
            db = ListenerDB(Path.cwd())
            all_proposals = db.all_proposals()
            sorted_proposals = sorted(all_proposals.keys())
            for p in sorted_proposals:
                if len(all_proposals[p]) > 1:
                    print(f"p{p}:")
                    for x in all_proposals[p]:
                        print("   ", x.db_dir, "" if x.official else " (unofficial)", sep="")
                else:
                    x = all_proposals[p][0]
                    print(f"p{p}: {x.db_dir}", "" if x.official else "(unofficial)")

    elif args.subcmd == "combiner":
        if args.combiner_subcmd == 'run':
            from .backend.combine import main
            return main()
        elif args.combiner_subcmd == 'now':
            from .backend.combine import gather_all_fragments
            gather_all_fragments(args.db_dir)

    elif args.subcmd == 'reprocess':
        # Hide some logging from Kafka to make things more readable
        logging.getLogger('kafka').setLevel(logging.WARNING)

        from .backend.extraction_control import reprocess
        reprocess(
            args.run, args.proposal, args.match, args.mock, args.watch, args.direct,
            limit_running=args.concurrent_jobs,
        )

    elif args.subcmd == 'read-context':
        from .backend.extract_data import Extractor
        Extractor(connect_to_kafka=not args.no_kafka).update_db_vars()

    elif args.subcmd == 'proposal':
        from .backend.db import DamnitDB
        db = DamnitDB()
        currently_set = db.metameta.get('proposal', None)
        if args.proposal is None:
            print("Current proposal number:", currently_set)
        elif args.proposal == currently_set:
            print(f"No change - proposal {currently_set} already set")
        else:
            db.metameta['proposal'] = args.proposal
            print(f"Changed proposal to {args.proposal} (was {currently_set})")

    elif args.subcmd == 'new-id':
        from secrets import token_hex
        from .backend.db import DamnitDB

        db = DamnitDB.from_dir(args.db_dir)
        db.metameta["db_id"] = token_hex(20)

    elif args.subcmd == 'db-config':
        from .backend.db import DamnitDB

        db = DamnitDB()
        handle_config_args(args, db.metameta)

    elif args.subcmd == "sample-data":
        from .sample_data import generate_sample_data

        proposal, runs = generate_sample_data(
            args.db_dir,
            runs=args.runs,
            start_run=args.start_run,
            proposal=args.proposal,
            seed=args.seed,
        )
        print(
            f"Generated {len(runs)} synthetic runs for p{proposal}: "
            f"{runs[0]}-{runs[-1]}"
        )

    elif args.subcmd == "site-config":
        if args.site_config_subcmd == "show":
            cfg = load_site_config(args.directory)
            print(json.dumps(cfg, indent=2, sort_keys=True))
        elif args.site_config_subcmd == "init":
            cfg_path, env_example_path = write_site_config_template(
                args.directory, profile=args.profile, force=args.force
            )
            print(f"Wrote {cfg_path}")
            print(f"Wrote {env_example_path}")

    elif args.subcmd == "migrate":
        from .backend.db import DamnitDB
        from .migrations import migrate_intermediate_v1, migrate_v0_to_v1

        db = DamnitDB(allow_old=True)

        if args.migrate_subcmd == "v0-to-v1":
            migrate_v0_to_v1(db, Path.cwd(), args.dry_run)
        elif args.migrate_subcmd == "intermediate-v1":
            migrate_intermediate_v1(db, Path.cwd(), args.dry_run)

if __name__ == '__main__':
    sys.exit(main())
