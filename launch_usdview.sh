#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    echo 'Usage: bash launch_usdview.sh [stage.usda] [usdview options]'
    echo 'With no arguments, opens the biped with Live Graph and Threads.'
    echo 'Set RIG to use another usdRig checkout; USD and PY override dependencies.'
    echo 'Set RIGEXEC_VIZ_RIG to select a specific rig prim path.'
    exit 0
fi
export RIGEXEC_VIZ_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export RIGEXEC_VIZ_AUTOOPEN=1
export RIG="${RIG:-$RIGEXEC_VIZ_ROOT/../usdRig}"
if [[ ! -f "$RIG/bin/usdview.sh" ]]; then
    echo 'usdRig launcher not found. Set RIG to your usdRig checkout.' >&2
    exit 1
fi
if [[ $# == 0 ]]; then
    set -- "$RIG/examples/biped/Biped_stack.usda"
fi
exec bash "$RIG/bin/usdview.sh" "$@"
