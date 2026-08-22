"""WorkspaceFS — deep module owning filesystem policy.

Single owner for: workdir containment, atomic verified writes, parent
creation, .trash timestamp moves, .bak backup/undo, range reads and
truncation, directory enumeration.

Interface is the ergonomic C shape from the Design-It-Twice review:
  read/write are 1-liners for the 80% path, other verbs are progressive
  disclosure. Typed errors (from design B) let LLM adapters stringify
  while tests get stack traces. One private _resolve/_verify seam (from
  design A) owns containment — tested once, exercised for free by every
  public method.

Dependencies: In-process (Path ops) + Local-substitutable (real FS via
injected root Path == tmp_path in tests). No external port needed —
the only variation is which directory, a constructor arg.
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ── errors ───────────────────────────────────────────────────────────────

class WorkspaceError(Exception):
    """Base for all workspace failures."""


class OutsideWorkspaceError(WorkspaceError):
    """Resolved path escapes the workspace root."""


class NotFoundError(WorkspaceError, FileNotFoundError):
    """Target does not exist."""


class IsDirectoryError(WorkspaceError):
    """Expected a file but found a directory."""


class VerificationFailed(WorkspaceError):
    """Post-write re-read did not match expected bytes."""


class TrashMiss(WorkspaceError):
    """No matching trash entry."""


# ── supporting types ─────────────────────────────────────────────────────

TIMESTAMP_FMT = "%Y%m%d_%H%M%S"


@dataclass(frozen=True, slots=True)
class TrashEntry:
    name: str  # file name inside .trash (e.g. "notes.md.20250507_120000")
    original: str  # original stem (e.g. "notes.md")
    path: Path  # absolute path inside .trash
    trashed_at: datetime


@dataclass(frozen=True, slots=True)
class DirEntry:
    name: str
    path: Path  # absolute
    is_dir: bool
    size: int


def _workdir_from_env() -> Path:
    # Mirrors builtin._get_workdir logic without importing builtin (avoid cycle).
    # Preference: MICRON_WORKDIR env → Config.workdir → cwd.
    env_val = os.getenv("MICRON_WORKDIR")
    if not env_val:
        try:
            from micron.config import Config

            env_val = Config().get("workdir") or os.getcwd()
        except Exception:
            env_val = os.getcwd()
    return Path(env_val).resolve()


def _get_trash_dir(root: Path) -> Path:
    d = root / ".trash"
    d.mkdir(exist_ok=True)
    return d


class WorkspaceFS:
    """Deep module — one seam at WorkspaceFS(root).

    Args:
        root: workspace root. None → MICRON_WORKDIR env → Config → cwd.
              Frozen after construction; every public method funnels through
              _resolve(path) which does containment via resolve()+is_relative_to.
    """

    def __init__(self, root: Path | str | None = None):
        if root is None:
            resolved = _workdir_from_env()
        else:
            resolved = Path(root).resolve()
        self._root: Path = resolved
        # Ensure root exists (mirrors builtin behaviour where parent mkdir is used).
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── internal seams (not part of public interface) ─────────────────

    def _resolve(self, user_path: str | Path) -> Path:
        """Resolve user_path relative to root and enforce containment."""
        if user_path is None:
            user_path = "."
        p = str(user_path)
        # Empty or "." stays at root.
        try:
            target = (self._root / p).resolve()
        except Exception as e:
            raise WorkspaceError(f"Error resolving path {p!r}: {e}") from e
        try:
            # Python 3.9+: Path.is_relative_to
            if target != self._root and not target.is_relative_to(self._root):
                raise OutsideWorkspaceError(f"Path {p!r} escapes the working directory.")
        except AttributeError:
            # Fallback for <3.9
            root_s = str(self._root)
            targ_s = str(target)
            if targ_s != root_s and not targ_s.startswith(root_s + os.sep):
                raise OutsideWorkspaceError(f"Path {p!r} escapes the working directory.")
        return target

    def _verify(self, path: Path, expected: str | bytes) -> None:
        """Re-read and compare. Raises VerificationFailed."""
        try:
            if isinstance(expected, bytes):
                actual = path.read_bytes()
                if actual != expected:
                    raise VerificationFailed(
                        f"post-write verification failed for {path.name}: expected {len(expected)} bytes, got {len(actual)}"
                    )
            else:
                actual = path.read_text(encoding="utf-8")
                if actual != expected:
                    snippet = actual[:150].replace("\n", "\\n")
                    raise VerificationFailed(
                        f"post-write verification failed for {path.name}: written content mismatch. File now starts with: {snippet}..."
                    )
        except VerificationFailed:
            raise
        except Exception as e:
            raise VerificationFailed(f"could not re-read {path.name} for verification: {e}") from e

    def _backup(self, target: Path) -> Path | None:
        """Create .bak backup. Returns backup path or None if source missing."""
        if not target.exists() or target.is_dir():
            return None
        # Auto-cleanup old .bak (>7 days)
        bak_path = target.with_suffix(target.suffix + ".bak")
        try:
            if bak_path.exists() and (time.time() - bak_path.stat().st_mtime) > 7 * 86400:
                bak_path.unlink()
        except Exception:
            pass
        # Also clean any generic .bak sibling (covers extensionless files)
        try:
            generic = Path(str(target) + ".bak")
            if generic != bak_path and generic.exists() and (time.time() - generic.stat().st_mtime) > 7 * 86400:
                generic.unlink()
        except Exception:
            pass
        shutil.copy2(str(target), str(bak_path))
        return bak_path

    def _move_to_trash(self, target: Path) -> TrashEntry:
        trash_dir = _get_trash_dir(self._root)
        ts = datetime.now().strftime(TIMESTAMP_FMT)
        trash_name = f"{target.name}.{ts}"
        trash_path = trash_dir / trash_name
        shutil.move(str(target), str(trash_path))
        if target.exists():
            raise WorkspaceError(f"{target.name} still exists after move to trash")
        if not trash_path.exists():
            raise WorkspaceError(f"{target.name} not found in trash after move")
        dt = datetime.strptime(ts, TIMESTAMP_FMT)
        return TrashEntry(name=trash_name, original=target.name, path=trash_path, trashed_at=dt)

    # ── public interface ───────────────────────────────────────────────

    # 80% path — read/write

    def read(
        self,
        path: str | Path,
        *,
        offset: int = 0,
        limit: int | None = None,
        max_bytes: int | None = 500_000,
        start_line: int = 0,
        end_line: int = 0,
    ) -> str:
        """Read a file (or list a directory when path is a dir).

        For file paths:
          - offset/limit are aliases for start_line/end_line (1-indexed for
            backwards compat with builtin.read_file). 0/None means from start.
          - When either start_line/end_line or offset/limit is supplied,
            returns that line range with a header: "--- path (lines a-b of N) ---\\n…"
          - Otherwise returns full content, truncated at max_bytes if needed.
            PDFs are extracted via pymupdf when available; binary files return
            a short descriptor instead of mojibake. Large files (>500 lines)
            are shown as first 250 + last 50 with omission marker (mirrors builtin).

        For directory paths: delegates to list(path) formatted as newline names.

        Raises OutsideWorkspaceError, NotFoundError.
        """
        # Normalise alias: offset/limit map to start_line/end_line
        if start_line == 0 and end_line == 0 and (offset or limit is not None):
            start_line = offset if offset else 0
            if limit is not None:
                # offset is 0-indexed in C design, but builtin uses start_line.
                # Map offset->start_line+1 for compat.
                if start_line:
                    end_line = start_line + limit
                    # start_line was 0-indexed offset; convert to 1-indexed
                    # builtin's read_file used start_line 1-indexed. C design offset 0-indexed.
                    # Keep compat: treat offset as already 1-indexed if caller passes start_line-style?
                    # Simplified: if offset provided, treat as start_line.
                    pass
                else:
                    end_line = limit
            else:
                end_line = 0

        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Path {str(path)!r} does not exist.")
        if target.is_dir():
            # Directory read → list
            entries = self.list(path)
            if not entries:
                return "Directory is empty."
            return "\n".join(e.name for e in entries)

        # PDF branch
        if target.suffix.lower() == ".pdf":
            return self._read_pdf(target, str(path), start_line=start_line, end_line=end_line, max_bytes=max_bytes)

        try:
            # Try text
            lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            try:
                data = target.read_bytes()
                return f"--- {path} (binary file, {len(data)} bytes) ---\n[Binary content — cannot display as text]"
            except Exception as e:
                raise WorkspaceError(f"Error reading file: {e}") from e
        except Exception as e:
            raise WorkspaceError(f"Error reading file: {e}") from e

        total = len(lines)
        # Range mode
        if start_line or end_line:
            start = max(0, (start_line or 1) - 1)
            end = end_line if end_line else total
            selected = lines[start:end]
            header = f"--- {path} (lines {start+1}-{min(end, total)} of {total}) ---\n"
            return header + "".join(selected)

        # Full file — large-file truncation mirrors builtin
        if total > 500:
            head = lines[:250]
            tail = lines[-50:]
            header = f"--- {path} ({total} lines, showing first 250 + last 50) ---\n"
            return header + "".join(head) + f"\n... ({total - 300} lines omitted) ...\n" + "".join(tail)

        content = "".join(lines)
        if max_bytes is not None and len(content) > max_bytes:
            return content[:max_bytes] + f"\n... [truncated {len(content)-max_bytes} bytes] ..."
        return content

    def _read_pdf(self, target: Path, display_path: str, *, start_line: int, end_line: int, max_bytes: int | None) -> str:
        try:
            import pymupdf  # type: ignore

            doc = pymupdf.open(str(target))
            total_pages = len(doc)
            pages_lines: list[str] = []
            for i, page in enumerate(doc):
                pages_lines.append(f"--- Page {i+1}/{total_pages} ---")
                pages_lines.append(page.get_text())
                pages_lines.append("")
            doc.close()
            text = "\n".join(pages_lines)
            if start_line or end_line:
                all_lines = text.splitlines(keepends=True)
                start = max(0, (start_line or 1) - 1)
                end = end_line if end_line else len(all_lines)
                return f"--- {display_path} (PDF, pages {start+1}-{min(end, len(all_lines))} of {len(all_lines)}) ---\n" + "".join(all_lines[start:end])
            if len(pages_lines) > 500:
                return f"--- {display_path} (PDF, {total_pages} pages, showing first 250 + last 50 lines) ---\n" + "\n".join(pages_lines[:250]) + f"\n... ({len(pages_lines) - 300} lines omitted) ...\n" + "\n".join(pages_lines[-50:])
            if max_bytes is not None and len(text) > max_bytes:
                return text[:max_bytes] + f"\n... [truncated {len(text)-max_bytes} bytes] ..."
            return text
        except ImportError:
            raise WorkspaceError("PDF extraction requires pymupdf. Install with: pip install pymupdf") from None
        except WorkspaceError:
            raise
        except Exception as e:
            raise WorkspaceError(f"Error reading PDF: {e}") from e

    def write(
        self,
        path: str | Path,
        content: str | bytes,
        *,
        create_dirs: bool = True,
        mode: str = "w",
        verify: bool = True,
    ) -> Path:
        """Atomic write (or append). Creates parents, verifies by re-read.

        Returns absolute Path written. Raises OutsideWorkspaceError,
        VerificationFailed, WorkspaceError.
        """
        target = self._resolve(path)
        if isinstance(content, bytes):
            # bytes path — raw write
            if create_dirs:
                target.parent.mkdir(parents=True, exist_ok=True)
            pre = None
            if mode == "a" and target.exists():
                try:
                    pre = target.read_bytes()
                except Exception:
                    pre = None
            # Atomic tmp+rename for "w", direct append for "a"
            if mode == "w":
                tmp = target.with_suffix(target.suffix + ".tmp")
                try:
                    tmp.write_bytes(content)
                    if verify:
                        self._verify(tmp, content)
                    tmp.replace(target)
                    if verify:
                        self._verify(target, content)
                finally:
                    try:
                        if tmp.exists() and tmp != target:
                            tmp.unlink()
                    except Exception:
                        pass
            else:
                with open(target, "ab") as f:
                    f.write(content)
                if verify and pre is not None:
                    self._verify(target, pre + content)
                elif verify:
                    self._verify(target, content)
            return target

        # str content
        text = content
        # For mode "a", capture pre for verification
        pre_text = None
        if mode == "a" and target.exists():
            try:
                pre_text = target.read_text(encoding="utf-8")
            except Exception:
                pre_text = None
        if create_dirs:
            target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "w":
            tmp = target.with_suffix(target.suffix + ".tmp") if target.suffix else Path(str(target) + ".tmp")
            # Handle extensionless tmp collision with .trash logic — ensure tmp is inside same dir
            if tmp == target:
                tmp = Path(str(target) + ".tmp")
            try:
                tmp.write_text(text, encoding="utf-8")
                if verify:
                    self._verify(tmp, text)
                tmp.replace(target)
                if verify:
                    self._verify(target, text)
            finally:
                try:
                    if tmp.exists() and tmp != target:
                        tmp.unlink()
                except Exception:
                    pass
        else:
            with open(target, "a", encoding="utf-8") as f:
                f.write(text)
            if verify:
                expected = (pre_text + text) if pre_text is not None else text
                self._verify(target, expected)
        return target

    # ── mutations with history ─────────────────────────────────────────

    def edit(self, path: str | Path, old: str, new: str, *, backup: bool = True, verify: bool = True) -> int:
        """Replace old with new (first occurrence like edit_file). Returns 1 if replaced, 0 if not found.

        Creates .bak backup before editing. Validates Python syntax via py_compile
        when path ends with .py (mirrors builtin behaviour).
        Raises OutsideWorkspaceError, NotFoundError, WorkspaceError on syntax revert.
        """
        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Path {str(path)!r} does not exist.")
        if target.is_dir():
            raise IsDirectoryError(f"Path {str(path)!r} is a directory.")
        content = target.read_text(encoding="utf-8")
        if old not in content:
            return 0
        # py_compile check before
        if str(path).endswith(".py"):
            import subprocess

            try:
                r = subprocess.run(["python3", "-m", "py_compile", str(target)], capture_output=True, text=True, timeout=5)
                if r.returncode != 0 and r.stderr:
                    raise WorkspaceError(f"Syntax error in {path} before editing: {r.stderr}")
            except WorkspaceError:
                raise
            except Exception:
                pass
        bak: Path | None = None
        if backup:
            bak = self._backup(target)
        new_content = content.replace(old, new, 1)
        target.write_text(new_content, encoding="utf-8")
        # py_compile after — revert on failure
        if str(path).endswith(".py"):
            import subprocess

            try:
                r = subprocess.run(["python3", "-m", "py_compile", str(target)], capture_output=True, text=True, timeout=5)
                if r.returncode != 0 and r.stderr:
                    if bak and bak.exists():
                        shutil.copy2(str(bak), str(target))
                    raise WorkspaceError(f"Syntax error after editing {path}: {r.stderr}")
            except WorkspaceError:
                raise
            except Exception:
                pass
        else:
            if verify:
                try:
                    self._verify(target, new_content)
                except VerificationFailed as e:
                    if bak and bak.exists():
                        shutil.copy2(str(bak), str(target))
                    raise WorkspaceError(str(e)) from e
        return 1

    def patch(self, path: str | Path, patches: list[dict], *, backup: bool = True) -> int:
        """Apply list of {old,new} patches sequentially. Returns count applied.

        Mirrors builtin.patch_file. Raises if none applied.
        """
        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Path {str(path)!r} does not exist.")
        content = target.read_text(encoding="utf-8")
        original = content
        applied = 0
        for patch in patches:
            old_text = patch.get("old", "")
            new_text = patch.get("new", "")
            if not old_text:
                continue
            if old_text in content:
                content = content.replace(old_text, new_text, 1)
                applied += 1
        if applied == 0:
            raise WorkspaceError("No patches applied: none of the 'old' texts were found in the file")
        bak = None
        if backup:
            bak = self._backup(target)
        target.write_text(content, encoding="utf-8")
        try:
            # verify changed
            actual = target.read_text(encoding="utf-8")
            if actual == original:
                raise VerificationFailed("patch verification failed: content unchanged")
        except VerificationFailed as e:
            if bak and bak.exists():
                shutil.copy2(str(bak), str(target))
            raise WorkspaceError(str(e)) from e
        return applied

    def delete(self, path: str | Path) -> TrashEntry:
        """Move file to .trash. Returns TrashEntry. Raises NotFoundError, IsDirectoryError."""
        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Path {str(path)!r} does not exist.")
        if target.is_dir():
            raise IsDirectoryError(f"Cannot delete directory {str(path)!r}: use run_command with rm -rf to delete directories")
        return self._move_to_trash(target)

    def trash(self) -> list[TrashEntry]:
        """List .trash entries sorted by name (chronological due to timestamp)."""
        trash_dir = self._root / ".trash"
        if not trash_dir.exists():
            return []
        entries: list[TrashEntry] = []
        for f in sorted(trash_dir.iterdir()):
            if not f.is_file():
                continue
            parts = f.name.rsplit(".", 1)
            ts_len = len(datetime.now().strftime(TIMESTAMP_FMT))
            if len(parts) == 2 and len(parts[1]) == ts_len:
                original = parts[0]
                try:
                    dt = datetime.strptime(parts[1], TIMESTAMP_FMT)
                except ValueError:
                    dt = datetime.fromtimestamp(f.stat().st_mtime)
            else:
                original = f.name
                dt = datetime.fromtimestamp(f.stat().st_mtime)
            entries.append(TrashEntry(name=f.name, original=original, path=f, trashed_at=dt))
        return entries

    def restore(self, name: str, *, dest: str | Path | None = None) -> Path:
        """Restore file from .trash by trash file name (with timestamp) or original name prefix.

        If dest provided, restore there; otherwise to root/<original>. Handles collisions with (1),(2) suffix.
        """
        trash_dir = _get_trash_dir(self._root)
        trash_path = trash_dir / name
        if not trash_path.exists():
            # partial match
            matches = list(trash_dir.glob(f"{name}.*"))
            if len(matches) == 1:
                trash_path = matches[0]
            elif len(matches) > 1:
                names = [m.name for m in matches]
                raise TrashMiss(f"Multiple files match {name!r}: {', '.join(names[:5])} — specify full name")
            else:
                raise TrashMiss(f"File {name!r} not found in trash. Use trash() to see available files")
        # Determine restore location
        if dest is not None:
            restore_path = self._resolve(dest)
        else:
            # strip timestamp suffix
            original_name = trash_path.name.rsplit(".", 1)[0] if "." in trash_path.name else trash_path.name
            # need to handle original that itself had dots — timestamp is last dot segment
            # If timestamp parse fails, keep full name as original
            parts = trash_path.name.rsplit(".", 1)
            ts_len = len(datetime.now().strftime(TIMESTAMP_FMT))
            if len(parts) == 2 and len(parts[1]) == ts_len:
                try:
                    datetime.strptime(parts[1], TIMESTAMP_FMT)
                    original_name = parts[0]
                except ValueError:
                    original_name = trash_path.name
            restore_path = self._root / original_name
            # If trash entry's original had subdirectory? builtin stored flat; keep flat.
        if restore_path.exists():
            counter = 1
            stem = trash_path.stem.rsplit(".", 1)[0] if "." in trash_path.stem else trash_path.stem
            # stem manipulation for collision
            base_stem = stem
            suffix = trash_path.suffix
            # For files like notes.md.20200101_120000, suffix is timestamp; use original ext
            # Re-derive from original_name
            orig_suffix = Path(original_name).suffix if 'original_name' in locals() else trash_path.suffix
            while restore_path.exists():
                restore_path = self._root / f"{base_stem}({counter}){orig_suffix}"
                counter += 1
        shutil.move(str(trash_path), str(restore_path))
        return restore_path

    def purge_trash(self) -> int:
        """Delete all files in .trash. Returns count purged."""
        trash_dir = self._root / ".trash"
        if not trash_dir.exists():
            return 0
        files = list(trash_dir.iterdir())
        if not files:
            return 0
        count = len(files)
        shutil.rmtree(str(trash_dir))
        return count

    def undo(self, path: str | Path) -> Path:
        """Restore .bak backup. Returns restored path. Raises TrashMiss if no backup."""
        target = self._resolve(path)
        # builtin used target.with_suffix(target.suffix + ".bak")
        bak_path = target.with_suffix(target.suffix + ".bak") if target.suffix else Path(str(target) + ".bak")
        if not bak_path.exists():
            # Also try generic
            alt = Path(str(target) + ".bak")
            if alt != bak_path and alt.exists():
                bak_path = alt
            else:
                raise TrashMiss(f"No backup found for {path!r}. edit creates .bak backups automatically")
        shutil.copy2(str(bak_path), str(target))
        try:
            bak_path.unlink()
        except Exception:
            pass
        return target

    def backup_path(self, path: str | Path) -> Path | None:
        target = self._resolve(path)
        bak = target.with_suffix(target.suffix + ".bak") if target.suffix else Path(str(target) + ".bak")
        if bak.exists():
            return bak
        alt = Path(str(target) + ".bak")
        if alt != bak and alt.exists():
            return alt
        return None

    # ── query ─────────────────────────────────────────────────────────

    def list(self, path: str | Path = ".") -> list[DirEntry]:
        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Path {str(path)!r} does not exist.")
        if not target.is_dir():
            raise IsDirectoryError(f"Path {str(path)!r} is not a directory.")
        entries: list[DirEntry] = []
        for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
            try:
                sz = p.stat().st_size if p.is_file() else 0
            except Exception:
                sz = 0
            entries.append(DirEntry(name=p.name, path=p, is_dir=p.is_dir(), size=sz))
        return entries

    def tree(self, path: str | Path = ".", *, max_depth: int = 3, show_files: bool = True, ext: str | None = None) -> str:
        target = self._resolve(path)
        if not target.exists():
            raise NotFoundError(f"Path {str(path)!r} does not exist.")

        def build(dir_path: Path, prefix: str = "", depth: int = 0) -> list[str]:
            if depth >= max_depth:
                return []
            lines: list[str] = []
            try:
                entries = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name))
            except PermissionError:
                return [f"{prefix}[Permission Denied]"]
            if not show_files:
                entries = [e for e in entries if e.is_dir()]
            if ext is not None:
                ext_dot = ext if ext.startswith(".") else f".{ext}"
                entries = [e for e in entries if e.is_dir() or e.suffix == ext_dot]
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                if entry.is_dir():
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    extension = "    " if is_last else "│   "
                    lines.extend(build(entry, prefix + extension, depth + 1))
                else:
                    lines.append(f"{prefix}{connector}{entry.name}")
            return lines

        result = [target.name + "/"]
        result.extend(build(target))
        return "\n".join(result)

    def exists(self, path: str | Path) -> bool:
        try:
            return self._resolve(path).exists()
        except WorkspaceError:
            return False

    def is_binary(self, path: str | Path) -> bool:
        target = self._resolve(path)
        try:
            data = target.read_bytes()[:1024]
            return b"\x00" in data
        except Exception:
            return False
