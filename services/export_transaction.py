"""Transactional export staging (M2.3).

Exports are written to a fresh staging directory below the destination
parent, validated there, and only then promoted to the final destination.
An existing non-empty destination is never deleted unless the caller
explicitly chooses overwrite or backup. A pre-created empty directory is
treated as a safe placeholder for the directory picker.
"""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class StagingPolicy:
    overwrite: bool = False
    backup: bool = False
    keep_failed: bool = False

    @classmethod
    def from_options(cls, overwrite: bool = False, backup: bool = False,
                     keep_failed: bool = False) -> "StagingPolicy":
        return cls(bool(overwrite), bool(backup), bool(keep_failed))


def validate_destination(destination: str) -> list:
    errors = []
    if not destination or not str(destination).strip():
        errors.append("destination must be a non-empty path")
        return errors
    dest = os.path.abspath(os.path.normpath(str(destination)))
    parent = os.path.dirname(dest)
    root = os.path.abspath(os.sep)
    if dest == parent or dest == root:
        errors.append("destination must not be a filesystem root: %s" % dest)
    drive, _tail = os.path.splitdrive(dest)
    if drive and dest == drive + os.sep:
        errors.append("destination must not be a drive root: %s" % dest)
    if os.path.basename(dest).startswith(".staging-"):
        errors.append("destination must not be a staging directory: %s" % dest)
    if os.path.isfile(dest):
        errors.append("destination exists as a file: %s" % dest)
    if not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            errors.append("cannot create destination parent %s: %s" % (parent, exc))
    return errors


def prepare_staging(destination: str) -> str:
    errors = validate_destination(destination)
    if errors:
        raise ValueError("; ".join(errors))
    dest = os.path.abspath(os.path.normpath(str(destination)))
    parent = os.path.dirname(dest)
    base = os.path.basename(dest) or "export"
    for _attempt in range(100):
        staging = os.path.join(parent, "%s.staging-%s" % (base, uuid.uuid4().hex[:12]))
        if not os.path.exists(staging):
            os.makedirs(staging)
            return staging
    raise RuntimeError("could not create a fresh staging directory below %s" % parent)


def backup_destination(destination: str) -> str:
    dest = os.path.abspath(os.path.normpath(str(destination)))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = "%s.backup-%s" % (dest, stamp)
    counter = 1
    final = candidate
    while os.path.exists(final):
        counter += 1
        final = "%s-%d" % (candidate, counter)
    os.rename(dest, final)
    return final


def _validate_staging_path(staging: str, destination: str) -> str:
    """Validate that *staging* is one of our directories below *destination*."""
    staging_abs = os.path.abspath(os.path.normpath(str(staging)))
    dest_abs = os.path.abspath(os.path.normpath(str(destination)))
    expected_parent = os.path.dirname(dest_abs)
    expected_prefix = os.path.basename(dest_abs) + ".staging-"
    if os.path.islink(staging_abs):
        raise ValueError("staging directory must not be a symbolic link: %s" % staging_abs)
    if not os.path.isdir(staging_abs):
        raise ValueError("staging directory does not exist: %s" % staging_abs)
    if os.path.normcase(os.path.dirname(staging_abs)) != os.path.normcase(expected_parent):
        raise ValueError("staging directory must be directly below the destination parent")
    if not os.path.basename(staging_abs).startswith(expected_prefix):
        raise ValueError("staging directory has an unexpected name: %s" % staging_abs)
    return staging_abs


def promote_staging(staging: str, destination: str, policy: StagingPolicy | None = None) -> str:
    policy = policy or StagingPolicy()
    errors = validate_destination(destination)
    if errors:
        raise ValueError("; ".join(errors))
    dest = os.path.abspath(os.path.normpath(str(destination)))
    staging_abs = _validate_staging_path(staging, dest)
    if staging_abs == dest:
        raise ValueError("staging directory must differ from the destination")
    replaced = None
    removed_empty_destination = False
    if os.path.exists(dest):
        if not os.path.isdir(dest):
            raise ValueError("destination exists as a file: %s" % dest)
        if policy.backup:
            backup_destination(dest)
        elif policy.overwrite:
            # Rename the old output first.  This keeps it recoverable if the
            # subsequent promotion fails, instead of deleting a known-good mod.
            replaced = "%s.replaced-%s" % (dest, uuid.uuid4().hex[:12])
            os.replace(dest, replaced)
        elif os.path.islink(dest):
            raise FileExistsError(
                "destination already exists as a symbolic link: %s "
                "(choose overwrite or backup to replace it)" % dest)
        else:
            try:
                is_empty = not os.listdir(dest)
            except OSError as exc:
                raise FileExistsError(
                    "destination already exists and cannot be inspected: %s "
                    "(choose overwrite or backup to replace it)" % dest) from exc
            if not is_empty:
                raise FileExistsError(
                    "destination already exists and is not empty: %s "
                    "(choose overwrite or backup to replace it)" % dest)
            # QFileDialog.getExistingDirectory returns a path that already
            # exists, even when the user just created a new empty folder.
            # Removing only that empty placeholder lets the staged directory
            # take its place without weakening protection for real exports.
            os.rmdir(dest)
            removed_empty_destination = True
    try:
        try:
            os.replace(staging_abs, dest)
        except OSError:
            shutil.move(staging_abs, dest)
    except Exception:
        if replaced is not None and os.path.exists(replaced) and not os.path.exists(dest):
            os.replace(replaced, dest)
        elif removed_empty_destination and not os.path.exists(dest):
            try:
                os.makedirs(dest)
            except OSError:
                pass
        raise
    if replaced is not None:
        shutil.rmtree(replaced, ignore_errors=True)
    return dest


def discard_staging(staging: str, keep_failed: bool = False) -> str | None:
    staging_abs = os.path.abspath(os.path.normpath(str(staging)))
    if (os.path.islink(staging_abs) or not os.path.isdir(staging_abs)
            or ".staging-" not in os.path.basename(staging_abs)):
        raise ValueError("refusing to discard a non-staging directory: %s" % staging_abs)
    if keep_failed:
        return staging_abs
    shutil.rmtree(staging_abs, ignore_errors=True)
    return None


def run_staged_export(destination: str, worker, policy: StagingPolicy | None = None) -> str:
    policy = policy or StagingPolicy()
    staging = prepare_staging(destination)
    try:
        worker(staging)
    except Exception as exc:
        leftover = discard_staging(staging, keep_failed=policy.keep_failed)
        if leftover is not None:
            raise RuntimeError("export failed; failed staging kept at %s: %s" % (leftover, exc)) from exc
        raise
    try:
        return promote_staging(staging, destination, policy)
    except Exception:
        discard_staging(staging, keep_failed=policy.keep_failed)
        raise
