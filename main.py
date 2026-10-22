import sys

from run_monitor import main as run_monitor_main


def main():
    args = ["run_monitor.py", "--once"]
    if len(sys.argv) > 1:
        args.extend(["--website-url", sys.argv[1]])
    if len(sys.argv) > 2:
        args.extend(["--website-name", sys.argv[2]])
    if len(sys.argv) > 3:
        args.extend(["--private-email-mode", sys.argv[3]])
    sys.argv = args
    run_monitor_main()


if __name__ == "__main__":
    main()