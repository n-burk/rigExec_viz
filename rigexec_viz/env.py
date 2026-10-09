"""Environment bootstrap: make pxr, rigexec and UsdNoodles importable.

Resolves everything from this checkout's siblings (``usd-install`` and
``usdRig/build`` next to ``rigExec_viz``) unless overridden:

* ``RIGEXEC_USD_INSTALL`` -- the USD install root (default: ``<work>/usd-install``)
* ``RIGEXEC_VIZ_BUILD`` -- the usdRig build root (default: ``<work>/usdRig/build``)

Must run before the first ``pxr`` import: it puts the install's
site-packages first, registers the native DLL directories, and drops the
meta-path finders that would otherwise claim top-level ``pxr`` for an
unrelated tree (a pip usd-core's redirect hook outranks ``sys.path``).

On success the rigExec schema plugin is registered as well, which must
happen before any stage is created or opened.
"""

import os
import pathlib
import sys

_DLL_DIR_HANDLES = []


def work_roots():
    """(usd_install, build_root) from the environment or the checkout layout."""
    here = pathlib.Path(__file__).resolve().parent
    # <work>/rigExec_viz/rigexec_viz/env.py -> <work>
    work = here.parents[1]
    usd_install = pathlib.Path(
        os.environ.get("RIGEXEC_USD_INSTALL") or (work / "usd-install"))
    build_root = pathlib.Path(
        os.environ.get("RIGEXEC_VIZ_BUILD") or (work / "usdRig" / "build"))
    return usd_install, build_root


def _prepend(path):
    text = str(path)
    if os.path.isdir(text) and text not in sys.path:
        sys.path.insert(0, text)


def _scrub_foreign_pxr_finders(usd_install):
    home = os.path.normcase(os.path.normpath(str(usd_install)))

    def _claimed_outside(spec):
        locations = getattr(spec, "submodule_search_locations", None) or []
        parts = [spec.origin or ""]
        parts.extend(str(location) for location in locations)
        claimed = os.path.normcase("\n".join(
            os.path.normpath(part) for part in parts if part))
        return home not in claimed

    for finder in list(sys.meta_path):
        find_spec = getattr(finder, "find_spec", None)
        if find_spec is None:
            continue
        try:
            spec = finder.find_spec("pxr", None)
        except Exception:  # noqa: BLE001 -- a raising finder keeps its place
            continue
        if spec is not None and _claimed_outside(spec):
            sys.meta_path.remove(finder)
    module = sys.modules.get("pxr")
    spec = getattr(module, "__spec__", None)
    if module is not None and spec is not None and _claimed_outside(spec):
        for name in [n for n in sys.modules
                     if n == "pxr" or n.startswith("pxr.")]:
            del sys.modules[name]


def setup(register_schema=True):
    """Prepare the interpreter; returns ``(usd_install, build_root)``.

    Idempotent: every step is a no-op when the ambient environment
    already carries the entry.
    """
    usd_install, build_root = work_roots()

    _prepend(usd_install / "Lib" / "site-packages")
    for candidate in sorted(usd_install.glob("lib/python*/site-packages")):
        _prepend(candidate)

    py_dir = build_root / "python"
    if py_dir.is_dir():
        _prepend(py_dir)

    if hasattr(os, "add_dll_directory"):
        for d in (usd_install / "lib", usd_install / "bin", build_root):
            try:
                if pathlib.Path(d).is_dir():
                    _DLL_DIR_HANDLES.append(os.add_dll_directory(str(d)))
            except OSError:
                pass

    _scrub_foreign_pxr_finders(usd_install)

    if register_schema:
        import rigexec  # noqa: E402 -- importable only after the setup above

        rigexec.load_schema_plugin()

    return usd_install, build_root
