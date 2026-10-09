"""Launch usdview with the live graph plugin; never create a second evaluator."""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage')
    parser.add_argument('--rig', default='')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2] / 'usdRig')
    args, flags = parser.parse_known_args()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, RIGEXEC_VIZ_ROOT=str(root), RIGEXEC_VIZ_AUTOOPEN='1', RIGEXEC_VIZ_RIG=args.rig)
    helper = args.repo / 'bin' / ('launch_usdview.bat' if os.name == 'nt' else 'usdview.sh')
    if not helper.is_file():
        parser.error('usdRig launcher not found; pass --repo')
    command = [str(helper), str(Path(args.stage).resolve()), *flags]
    raise SystemExit(subprocess.call(command, env=env))


if __name__ == '__main__':
    main()
