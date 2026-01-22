# src/pipeline/file_manager.py

"""
File Management Operations
Business logic for file and folder operations in the data directory
"""

import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any # 251205–BundB Jun: Added Any
import json
from datetime import datetime  # 251210–BundB Jun: for created_at sorting

from pydantic import BaseModel, Field

# ============================================================
# PYDANTIC MODELS
# ============================================================


class DeleteFilesRequest(BaseModel):
    """Request to delete multiple files from a folder"""

    folder_name: str = Field(..., description="Folder path (e.g., 'data/user01')")
    filenames: List[str] = Field(..., description="List of filenames to delete")


class DeleteFilesResponse(BaseModel):
    """Response for file deletion"""

    folder_name: str
    total_requested: int
    deleted: int
    not_deleted: int
    deleted_files: List[str]
    not_deleted_files: List[Dict[str, str]]  # filename + reason


class DeleteFolderRequest(BaseModel):
    """Request to delete a folder"""

    folder_name: str = Field(..., description="Folder path to delete (e.g., 'data/user01')")


class DeleteFolderResponse(BaseModel):
    """Response for folder deletion"""

    folder_name: str
    deleted: bool
    message: str
    files_deleted: int


class FileTreeItem(BaseModel):
    """Single item in file tree"""

    name: str
    type: str  # "file" or "directory"
    path: str
    size_bytes: Optional[int] = None
    children: Optional[List["FileTreeItem"]] = None
    metadata: Optional[Dict[str, Any]] = None # 251205–BundB Jun: add flexible per-file metadata (from _metadata/*.json)


class GetUserFilesResponse(BaseModel):
    """Response with file tree"""

    folder_name: str
    total_files: int
    total_directories: int
    total_size_bytes: int
    tree: List[FileTreeItem]

# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# 251210–BundB Jun – BEGIN
class GetUserFilesFlatResponse(BaseModel):
    """
    Response with flat, paginated file list

    - files: Flat list of files only (no directories)
    - page / limit: Pagination info
    - has_more: Whether more pages are available
    """

    folder_name: str
    total_files: int              # total files AFTER search filter
    total_directories: int        # directories scanned (for info)
    total_size_bytes: int         # sum of size_bytes for filtered files
    page: int
    limit: int
    has_more: bool
    files: List[FileTreeItem]
# 251210–BundB Jun – END
# ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

# ============================================================
# EXCEPTIONS
# ============================================================


class FileManagerError(Exception):
    """Base exception for file manager operations"""

    pass


class InvalidPathError(FileManagerError):
    """Raised when path is invalid or unsafe"""

    pass


class ProtectedPathError(FileManagerError):
    """Raised when trying to delete protected paths"""

    pass


class PathNotFoundError(FileManagerError):
    """Raised when path does not exist"""

    pass


# ============================================================
# FILE MANAGER CLASS
# ============================================================


class FileManager:
    """
    Manages file and folder operations in the data directory
    with safety checks and path validation
    """

    def __init__(self, data_root: str = "data"):
        """
        Initialize file manager

        Args:
            data_root: Root directory for file operations (default: "data")
        """
        self.data_root = Path(data_root).resolve()

        # Ensure data root exists
        self.data_root.mkdir(parents=True, exist_ok=True)

        # Protected directories that cannot be deleted
        self.protected_dirs = {
            self.data_root,  # Root data folder
        }

        # Directories to skip in tree view
        self.skip_dirs = {"_metadata", "_jobs", "_pipeline", "__pycache__", ".git", ".venv"}

    def validate_path(self, folder_path: str) -> Path:
        """
        Validate and sanitize folder path to prevent path traversal attacks

        Args:
            folder_path: Path to validate

        Returns:
            Validated Path object

        Raises:
            InvalidPathError: If path is invalid or unsafe
        """
        # Remove leading/trailing slashes and whitespace
        folder_path = folder_path.strip().strip("/")

        # Check for path traversal attempts
        if ".." in folder_path or folder_path.startswith("/"):
            raise InvalidPathError("Path traversal not allowed")

        # Normalize path relative to data root
        if folder_path and not folder_path.startswith(self.data_root.name):
            folder_path = f"{self.data_root.name}/{folder_path}"

        # Resolve to absolute path
        path = Path(folder_path).resolve()

        # Ensure path is within data directory
        try:
            path.relative_to(self.data_root)
        except ValueError:
            raise InvalidPathError(f"Path must be within {self.data_root.name} directory")

        return path

    def is_protected(self, path: Path) -> bool:
        """Check if path is protected from deletion"""
        return path.resolve() in self.protected_dirs

    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # 251202–BundB Jun – BEGIN
    def _delete_pipeline_artifacts_for_file(self, folder_path: Path, clean_filename: str) -> None:
        """
        Delete _pipeline artifacts that belong to the given filename.

        - Look into: <folder_path>/_pipeline/step1_processed/metadata/*.json
        - Match by JSON metadata:
          * filename == clean_filename
          * original_filename == clean_filename
          * OR clean_filename is included in file_path
        - Use the metadata filename stem as base key, and delete related files in:
          * step1_processed/texts
          * step1_processed/metadata
          * step2_entities
          * step3_chunks/chunks
          * step5_linked
        """
        pipeline_dir = folder_path / "_pipeline"
        if not pipeline_dir.exists() or not pipeline_dir.is_dir():
            return

        step1_meta_dir = pipeline_dir / "step1_processed" / "metadata"
        if not step1_meta_dir.exists() or not step1_meta_dir.is_dir():
            return

        # 001 - Find base names in step1 metadata that reference the given filename
        basenames: List[str] = []

        for meta_path in step1_meta_dir.glob("*.json"):
            try:
                with meta_path.open("r", encoding="utf-8") as f:
                    meta_json = json.load(f)
            except Exception:
                # Skip file if JSON parsing fails
                continue

            meta_filename = str(meta_json.get("filename") or "")
            meta_original = str(meta_json.get("original_filename") or "")
            meta_file_path = str(meta_json.get("file_path") or "")

            # 002 - Match by filename or original_filename or file_path
            if (
                clean_filename == meta_filename
                or clean_filename == meta_original
                or clean_filename in meta_file_path
            ):
                basenames.append(meta_path.stem)

        if not basenames:
            return

        # 003 - Delete related pipeline artifacts for each found base name
        for base in basenames:
            # step1_processed/texts/<base>.txt
            step1_text_dir = pipeline_dir / "step1_processed" / "texts"
            if step1_text_dir.exists() and step1_text_dir.is_dir():
                txt_path = step1_text_dir / f"{base}.txt"
                if txt_path.exists():
                    try:
                        txt_path.unlink()
                    except Exception:
                        pass

            # step1_processed/metadata/<base>.json
            meta_json_path = step1_meta_dir / f"{base}.json"
            if meta_json_path.exists():
                try:
                    meta_json_path.unlink()
                except Exception:
                    pass

            # step2_entities/<base>_entities.json
            step2_dir = pipeline_dir / "step2_entities"
            if step2_dir.exists() and step2_dir.is_dir():
                entities_path = step2_dir / f"{base}_entities.json"
                if entities_path.exists():
                    try:
                        entities_path.unlink()
                    except Exception:
                        pass

            # step3_chunks/chunks/<base>_chunks.json
            step3_chunks_dir = pipeline_dir / "step3_chunks" / "chunks"
            if step3_chunks_dir.exists() and step3_chunks_dir.is_dir():
                chunks_path = step3_chunks_dir / f"{base}_chunks.json"
                if chunks_path.exists():
                    try:
                        chunks_path.unlink()
                    except Exception:
                        pass

            # step5_linked/<base>_linked.json  (may not exist)
            step5_dir = pipeline_dir / "step5_linked"
            if step5_dir.exists() and step5_dir.is_dir():
                linked_path = step5_dir / f"{base}_linked.json"
                if linked_path.exists():
                    try:
                        linked_path.unlink()
                    except Exception:
                        pass
    # 251202–BundB Jun – END
    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––


    def delete_files(self, folder_name: str, filenames: List[str]) -> DeleteFilesResponse:
        """
        Delete multiple files from a folder

        Args:
            folder_name: Target folder path
            filenames: List of filenames to delete

        Returns:
            DeleteFilesResponse with results

        Raises:
            InvalidPathError: If folder path is invalid
            PathNotFoundError: If folder doesn't exist
        """
        # Validate folder path
        folder_path = self.validate_path(folder_name)

        if not folder_path.exists():
            raise PathNotFoundError(f"Folder not found: {folder_name}")

        if not folder_path.is_dir():
            raise InvalidPathError(f"Not a directory: {folder_name}")

        deleted_files = []
        not_deleted_files = []

        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        # 251201–BundB Jun – BEGIN
        # Metadata directory path (e.g., data/user01/_metadata)
        metadata_dir = folder_path / "_metadata"
        # 251201–BundB Jun – END
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

        for filename in filenames:
            try:
                # Sanitize filename (remove any path components)
                clean_filename = Path(filename).name
                file_path = folder_path / clean_filename

                # Check if file exists
                if not file_path.exists():
                    not_deleted_files.append({"filename": filename, "reason": "File not found"})
                    continue

                # Check if it's actually a file
                if not file_path.is_file():
                    not_deleted_files.append(
                        {"filename": filename, "reason": "Not a file (directory or special file)"}
                    )
                    continue

                # Security: Ensure file is within target folder
                if file_path.parent.resolve() != folder_path.resolve():
                    not_deleted_files.append(
                        {"filename": filename, "reason": "File outside target folder"}
                    )
                    continue

                # Delete file
                file_path.unlink()
                deleted_files.append(filename)

                # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
                # 251201–BundB Jun – BEGIN
                # Delete metadata file, if exists
                try:
                    if metadata_dir.exists() and metadata_dir.is_dir():
                        metadata_file = metadata_dir / f"{clean_filename}.json"
                        if metadata_file.exists() and metadata_file.is_file():
                            metadata_file.unlink()
                    # Even if the metadata file does not exist, we ignore the error
                except Exception:
                    # Ignore errors when deleting metadata file
                    pass
                # 251201–BundB Jun – END
                # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

                # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
                # 251202–BundB Jun – BEGIN
                # Delete related _pipeline artifacts (step1/2/3/5) if they reference this file
                try:
                    self._delete_pipeline_artifacts_for_file(folder_path, clean_filename)
                except Exception:
                    # Pipeline cleanup failure does not block main deletion
                    pass
                # 251202–BundB Jun – END
                # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

            except PermissionError:
                not_deleted_files.append({"filename": filename, "reason": "Permission denied"})
            except Exception as e:
                not_deleted_files.append({"filename": filename, "reason": str(e)})

        return DeleteFilesResponse(
            folder_name=folder_name,
            total_requested=len(filenames),
            deleted=len(deleted_files),
            not_deleted=len(not_deleted_files),
            deleted_files=deleted_files,
            not_deleted_files=not_deleted_files,
        )

    def delete_folder(self, folder_name: str) -> DeleteFolderResponse:
        """
        Delete entire folder and all its contents

        Args:
            folder_name: Folder path to delete

        Returns:
            DeleteFolderResponse with results

        Raises:
            InvalidPathError: If path is invalid
            ProtectedPathError: If trying to delete protected path
            PathNotFoundError: If folder doesn't exist
        """
        # Validate folder path
        folder_path = self.validate_path(folder_name)

        # Check if protected
        if self.is_protected(folder_path):
            raise ProtectedPathError(
                f"Cannot delete protected folder: {folder_name}. "
                f"Root '{self.data_root.name}' directory is protected."
            )

        if not folder_path.exists():
            raise PathNotFoundError(f"Folder not found: {folder_name}")

        if not folder_path.is_dir():
            raise InvalidPathError(f"Not a directory: {folder_name}")

        # Count files before deletion
        file_count = sum(1 for _ in folder_path.rglob("*") if _.is_file())

        # Delete folder and all contents
        shutil.rmtree(folder_path)

        return DeleteFolderResponse(
            folder_name=folder_name,
            deleted=True,
            message=f"Successfully deleted folder '{folder_name}' and all contents",
            files_deleted=file_count,
        )

    def _build_tree(self, path: Path) -> Tuple[List[FileTreeItem], int, int, int]:
        """
        Build file tree recursively

        Args:
            path: Root path to build tree from

        Returns:
            Tuple of (tree, file_count, dir_count, total_size)
        """
        if not path.exists():
            return [], 0, 0, 0

        tree = []
        total_files = 0
        total_dirs = 0
        total_size = 0

        try:
            # Sort: directories first, then files, alphabetically
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))

            # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
            # 251205–BundB Jun – BEGIN
            # For this directory, look for local _metadata folder
            metadata_dir = path / "_metadata"
            has_metadata_dir = metadata_dir.exists() and metadata_dir.is_dir()
            # 251205–BundB Jun – END
            # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

            for item in items:
                # Skip hidden items and metadata directories
                if item.name.startswith(".") or item.name in self.skip_dirs:
                    continue

                if item.is_file():
                    size = item.stat().st_size

                    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
                    # 251205–BundB Jun – BEGIN
                    # Try to load metadata from <current_dir>/_metadata/<filename>.json
                    file_metadata: Optional[Dict[str, Any]] = None
                    if has_metadata_dir:
                        meta_path = metadata_dir / f"{item.name}.json"
                        if meta_path.exists() and meta_path.is_file():
                            try:
                                with meta_path.open("r", encoding="utf-8") as f:
                                    loaded = json.load(f)
                                if isinstance(loaded, dict):
                                    file_metadata = loaded
                            except Exception as e:
                                # Metadata loading failure should never break tree listing
                                print(f"⚠️ Failed to load metadata for {item}: {e}")
                    # 251205–BundB Jun – END
                    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

                    tree.append(
                        FileTreeItem(
                            name=item.name,
                            type="file",
                            path=str(item.relative_to(self.data_root)),
                            size_bytes=size,
                            children=None,
                            metadata=file_metadata, # 251205–BundB Jun: attach metadata
                        )
                    )
                    total_files += 1
                    total_size += size

                elif item.is_dir():
                    # Recursively build tree for subdirectory
                    subtree, sub_files, sub_dirs, sub_size = self._build_tree(item)

                    tree.append(
                        FileTreeItem(
                            name=item.name,
                            type="directory",
                            path=str(item.relative_to(self.data_root)),
                            size_bytes=sub_size,
                            children=subtree if subtree else None,
                            metadata=None,  # 251205–BundB Jun: no metadata for directories
                        )
                    )
                    total_files += sub_files
                    total_dirs += 1 + sub_dirs
                    total_size += sub_size

        except PermissionError as e:
            print(f"⚠️ Permission denied accessing {path}: {e}")

        return tree, total_files, total_dirs, total_size

    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # 251210–BundB Jun – BEGIN
    def _collect_files_flat(
        self,
        path: Path,
    ) -> Tuple[List[FileTreeItem], int, int, int]:
        """
        Collect all files under given path as a flat list (no directory entries).

        Returns:
            (files, total_files, total_directories, total_size_bytes)
        """
        if not path.exists():
            return [], 0, 0, 0

        files: List[FileTreeItem] = []
        total_files = 0
        total_dirs = 0
        total_size = 0

        try:
            # Sort: directories first, then files, alphabetically
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))

            # For this directory, look for local _metadata folder
            metadata_dir = path / "_metadata"
            has_metadata_dir = metadata_dir.exists() and metadata_dir.is_dir()

            for item in items:
                # Skip hidden items and metadata directories
                if item.name.startswith(".") or item.name in self.skip_dirs:
                    continue

                if item.is_file():
                    size = item.stat().st_size

                    # Try to load metadata from <current_dir>/_metadata/<filename>.json
                    file_metadata: Optional[Dict[str, Any]] = None
                    if has_metadata_dir:
                        meta_path = metadata_dir / f"{item.name}.json"
                        if meta_path.exists() and meta_path.is_file():
                            try:
                                with meta_path.open("r", encoding="utf-8") as f:
                                    loaded = json.load(f)
                                if isinstance(loaded, dict):
                                    file_metadata = loaded
                            except Exception as e:
                                # Metadata loading failure should never break listing
                                print(f"⚠️ Failed to load metadata for {item}: {e}")

                    files.append(
                        FileTreeItem(
                            name=item.name,
                            type="file",
                            path=str(item.relative_to(self.data_root)),
                            size_bytes=size,
                            children=None,
                            metadata=file_metadata,
                        )
                    )
                    total_files += 1
                    total_size += size

                elif item.is_dir():
                    # Recursively collect from subdirectory
                    sub_files, sub_file_count, sub_dir_count, sub_size = self._collect_files_flat(item)
                    files.extend(sub_files)
                    total_files += sub_file_count
                    total_dirs += 1 + sub_dir_count
                    total_size += sub_size

        except PermissionError as e:
            print(f"⚠️ Permission denied accessing {path}: {e}")

        return files, total_files, total_dirs, total_size
    # 251210–BundB Jun – END
    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

    def get_file_tree(self, folder_name: str) -> GetUserFilesResponse:
        """
        Get hierarchical file tree structure

        Args:
            folder_name: Folder path to list

        Returns:
            GetUserFilesResponse with tree structure

        Raises:
            InvalidPathError: If path is invalid
            PathNotFoundError: If folder doesn't exist
        """
        # Validate folder path
        folder_path = self.validate_path(folder_name)

        if not folder_path.exists():
            raise PathNotFoundError(f"Folder not found: {folder_name}")

        if not folder_path.is_dir():
            raise InvalidPathError(f"Not a directory: {folder_name}")

        # Build tree
        tree, total_files, total_dirs, total_size = self._build_tree(folder_path)

        return GetUserFilesResponse(
            folder_name=folder_name,
            total_files=total_files,
            total_directories=total_dirs,
            total_size_bytes=total_size,
            tree=tree,
        )

    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # 251210–BundB Jun – BEGIN
    def get_file_list_flat(
        self,
        folder_name: str,
        page: int = 1,
        limit: int = 50,
        search: Optional[str] = None,
    ) -> GetUserFilesFlatResponse:
        """
        Get flat, paginated file list for a folder.

        - Only files are returned (no directories)
        - Optional search over filename + basic metadata (e.g., created_user_name)
        - Pagination performed AFTER search filter

        Args:
            folder_name: Folder path to list
            page: Page number (1-based)
            limit: Max items per page
            search: Optional search string (min 2 chars)

        Raises:
            InvalidPathError: If path is invalid
            PathNotFoundError: If folder doesn't exist
        """
        # Normalize pagination arguments
        try:
            page_int = int(page)
        except (TypeError, ValueError):
            page_int = 1

        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            limit_int = 50

        page_int = max(1, page_int)
        # Hard cap to avoid abuse
        limit_int = max(1, min(limit_int, 200))

        # Validate folder path
        folder_path = self.validate_path(folder_name)

        if not folder_path.exists():
            raise PathNotFoundError(f"Folder not found: {folder_name}")

        if not folder_path.is_dir():
            raise InvalidPathError(f"Not a directory: {folder_name}")

        # Collect flat list of files (no directories)
        all_files, total_files_all, total_dirs, total_size_all = self._collect_files_flat(folder_path)

        # Server-side search filtering (optional)
        search_raw = (search or "").strip().lower()
        if len(search_raw) >= 2:
            filtered_files: List[FileTreeItem] = []
            total_size_filtered = 0

            for f in all_files:
                name = (f.name or "").lower()
                meta = f.metadata or {}

                created_user_name = str(meta.get("created_user_name") or "").lower()
                created_user_id = str(meta.get("created_user_id") or "").lower()

                if (
                    search_raw in name
                    or search_raw in created_user_name
                    or search_raw in created_user_id
                ):
                    filtered_files.append(f)
                    total_size_filtered += f.size_bytes or 0
        else:
            filtered_files = all_files
            total_size_filtered = sum((f.size_bytes or 0) for f in filtered_files)

        total_filtered = len(filtered_files)

        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
        # 251210–BundB Jun – BEGIN: sort by latest first
        def _parse_created_ts(value: Any) -> Optional[float]:
            """Parse ISO datetime string to timestamp (seconds)."""
            if not isinstance(value, str) or not value:
                return None
            try:
                # Support ISO strings with trailing 'Z'
                v = value.strip()
                if v.endswith("Z"):
                    v = v[:-1]
                dt = datetime.fromisoformat(v)
                return dt.timestamp()
            except Exception:
                return None

        def _get_sort_timestamp(f: FileTreeItem) -> float:
            """
            Determine timestamp for sorting:
            1) metadata.created_at (if valid ISO string)
            2) filesystem mtime
            3) fallback: 0.0
            """
            meta = f.metadata or {}
            created_at = meta.get("created_at")

            ts_meta = _parse_created_ts(created_at)
            if ts_meta is not None:
                return ts_meta

            # Fallback: filesystem mtime
            try:
                full_path = self.data_root / f.path
                return full_path.stat().st_mtime
            except Exception:
                return 0.0

        # 최신 파일이 먼저 오도록 내림차순 정렬
        filtered_files.sort(key=_get_sort_timestamp, reverse=True)
        # 251210–BundB Jun – END
        # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

        # Pagination over filtered list
        offset = (page_int - 1) * limit_int
        page_items = filtered_files[offset : offset + limit_int]
        has_more = offset + limit_int < total_filtered

        return GetUserFilesFlatResponse(
            folder_name=folder_name,
            total_files=total_filtered,
            total_directories=total_dirs,
            total_size_bytes=total_size_filtered,
            page=page_int,
            limit=limit_int,
            has_more=has_more,
            files=page_items,
        )
    # 251210–BundB Jun – END
    # ––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––



# ============================================================
# SINGLETON INSTANCE
# ============================================================

# Global file manager instance
_file_manager: Optional[FileManager] = None


def get_file_manager() -> FileManager:
    """
    Get or create global FileManager instance

    Returns:
        FileManager instance
    """
    global _file_manager
    if _file_manager is None:
        _file_manager = FileManager()
    return _file_manager
