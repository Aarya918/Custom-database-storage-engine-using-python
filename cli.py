"""Tiny interactive shell:  python -m lsm.cli ./mydb"""
import argparse
import shlex

from . import LSMError, LSMStore

HELP = """commands: put KEY VALUE | get KEY | delete KEY | scan [START [END]]
          flush | compact | stats | help | quit"""


def main(argv=None):
    parser = argparse.ArgumentParser(description="LSM-Tree shell")
    parser.add_argument("path")
    parser.add_argument("--memtable-limit", type=int, default=1000)
    parser.add_argument("--no-sync", action="store_true", help="do not fsync every WAL write")
    args = parser.parse_args(argv)
    try:
        store = LSMStore(args.path, memtable_limit=args.memtable_limit, sync=not args.no_sync)
    except LSMError as exc:
        print(f"error: {exc}")
        return 2
    print(HELP)
    with store:
        while True:
            try:
                parts = shlex.split(input("lsm> "))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            except ValueError as exc:
                print(f"error: {exc}")
                continue
            if not parts:
                continue
            cmd, rest = parts[0].lower(), parts[1:]
            try:
                if cmd in ("quit", "exit"):
                    break
                elif cmd == "put" and len(rest) == 2:
                    store.put(*rest)
                    print("OK")
                elif cmd == "get" and len(rest) == 1:
                    print(store.get(rest[0]))
                elif cmd == "delete" and len(rest) == 1:
                    store.delete(rest[0])
                    print("OK")
                elif cmd == "scan" and len(rest) <= 2:
                    for k, v in store.scan(*rest):
                        print(f"{k} = {v}")
                elif cmd == "flush":
                    store.flush()
                    print("OK")
                elif cmd == "compact":
                    store.compact()
                    print("OK")
                elif cmd == "stats":
                    print(store.stats())
                else:
                    print(HELP)
            except LSMError as exc:
                print(f"error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
