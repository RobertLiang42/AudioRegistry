from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .i18n import t
from .models import Segment
from .review import REVIEW_SCHEMA_VERSION, build_review_document, validate_review

DATABASE_FILENAME = "audio-registry.sqlite3"
LEGACY_DATABASE_FILENAME = "voice-segmenter.sqlite3"
DATABASE_SCHEMA_VERSION = 9
DEFAULT_TAG = "1"
PROJECT_DATABASE_SUFFIX = ".sqlite3"
PROJECT_DATABASE_TABLES = {
    "schema_info",
    "sources",
    "segments",
    "review_snapshots",
    "audio_variants",
    "assembly_items",
}


def database_path_for(
    data_dir: str | Path,
    *,
    legacy_directories: Iterable[str | Path] = (),
) -> Path:
    """Return the new database path, or an existing legacy database.

    No file is moved automatically: existing user data keeps working while new
    installations store private data in the dedicated data directory.
    """
    directory = Path(data_dir).resolve()
    preferred = directory / DATABASE_FILENAME
    if preferred.is_file():
        return preferred
    candidates = (directory, *(Path(item).resolve() for item in legacy_directories))
    for candidate in candidates:
        legacy = candidate / LEGACY_DATABASE_FILENAME
        if legacy.is_file():
            return legacy
    return preferred


def project_workspace_for(project_name: str, output_dir: str | Path) -> Path:
    name = validate_project_name(project_name)
    return Path(output_dir).resolve() / name


def validate_project_name(value: str) -> str:
    name = str(value).strip()
    if not name:
        raise ValueError(t("errors.project_name_empty"))
    if any(character in name for character in '<>:"/\\|?*') or name in {".", ".."}:
        raise ValueError(t("errors.project_name_chars"))
    if name.endswith((" ", ".")):
        raise ValueError(t("errors.project_name_suffix"))
    return name


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ProjectDatabase:
    """Unified SQLite storage for timeline review and dataset assembly."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    audio_path TEXT NOT NULL COLLATE NOCASE,
                    audio_name TEXT NOT NULL,
                    audio_stem TEXT NOT NULL,
                    file_size INTEGER,
                    file_mtime_ns INTEGER,
                    review_schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ui_preferences_json TEXT,
                    project_name TEXT NOT NULL COLLATE NOCASE,
                    update_counter INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS segments (
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    segment_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    speaker TEXT,
                    text TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    manual_text INTEGER NOT NULL DEFAULT 0,
                    needs_asr INTEGER NOT NULL DEFAULT 0,
                    origin_ids_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (source_id, segment_id)
                );
                CREATE INDEX IF NOT EXISTS segments_source_time
                    ON segments(source_id, start, end, ordinal);
                CREATE TABLE IF NOT EXISTS review_snapshots (
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL,
                    saved_at TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    PRIMARY KEY (source_id, revision)
                );

                CREATE TABLE IF NOT EXISTS audio_variants (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    audio_path TEXT NOT NULL COLLATE NOCASE,
                    alignment_kind TEXT NOT NULL DEFAULT 'source_time',
                    created_at TEXT NOT NULL,
                    offset_seconds REAL NOT NULL DEFAULT 0,
                    time_scale REAL NOT NULL DEFAULT 1,
                    duration_seconds REAL,
                    file_size INTEGER,
                    file_mtime_ns INTEGER,
                    updated_at TEXT,
                    ordinal INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (source_id, name)
                );
                CREATE TABLE IF NOT EXISTS assembly_items (
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    segment_id TEXT NOT NULL,
                    selected_variant_id TEXT REFERENCES audio_variants(id) ON DELETE SET NULL,
                    tag TEXT NOT NULL DEFAULT '1',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, segment_id)
                );
                """
            )
            rows = connection.execute("SELECT version FROM schema_info").fetchall()
            if not rows:
                connection.execute(
                    "INSERT INTO schema_info(version) VALUES (?)",
                    (DATABASE_SCHEMA_VERSION,),
                )
                version = DATABASE_SCHEMA_VERSION
            elif len(rows) == 1:
                version = int(rows[0]["version"])
            else:
                raise RuntimeError(t("errors.database_schema"))
            if version == 1:
                self._upgrade_v1_to_v2(connection)
                version = 2
            if version == 2:
                self._upgrade_v2_to_v3(connection)
                version = 3
            if version == 3:
                self._upgrade_v3_to_v4(connection)
                version = 4
            if version == 4:
                # Foreign-key toggling is ignored inside a transaction.
                connection.commit()
                self._upgrade_v4_to_v5(connection)
                version = 5
            if version == 5:
                self._upgrade_v5_to_v6(connection)
                version = 6
            if version == 6:
                # Foreign-key toggling is ignored inside a transaction.
                connection.commit()
                self._upgrade_v6_to_v7(connection)
                version = 7
            if version == 7:
                # SQLite cannot alter a column default in place.
                connection.commit()
                self._upgrade_v7_to_v8(connection)
                version = 8
            if version == 8:
                # SQLite cannot alter a column default in place.
                connection.commit()
                self._upgrade_v8_to_v9(connection)
                version = 9
            if version != DATABASE_SCHEMA_VERSION:
                raise RuntimeError(t("errors.database_schema"))
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_project_name ON sources(project_name COLLATE NOCASE)"
            )
            self._install_counter_triggers(connection)
            self._remove_legacy_ui_preferences(connection)
            connection.execute("PRAGMA optimize")
            connection.commit()

    @staticmethod
    def _remove_legacy_ui_preferences(connection: sqlite3.Connection) -> None:
        """Remove browser state without changing project data or update counters."""
        connection.execute("UPDATE sources SET ui_preferences_json=NULL WHERE ui_preferences_json IS NOT NULL")
        for row in connection.execute(
            "SELECT source_id, revision, document_json FROM review_snapshots"
        ).fetchall():
            document = json.loads(row["document_json"])
            if isinstance(document, dict) and "ui_preferences" in document:
                document.pop("ui_preferences")
                connection.execute(
                    "UPDATE review_snapshots SET document_json=? WHERE source_id=? AND revision=?",
                    (json.dumps(document, ensure_ascii=False), row["source_id"], row["revision"]),
                )

    @staticmethod
    def _upgrade_v1_to_v2(connection: sqlite3.Connection) -> None:
        source_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sources)")}
        if "project_name" not in source_columns:
            connection.execute("ALTER TABLE sources ADD COLUMN project_name TEXT COLLATE NOCASE")
        variant_columns = {row["name"] for row in connection.execute("PRAGMA table_info(audio_variants)")}
        additions = {
            "offset_seconds": "REAL NOT NULL DEFAULT 0",
            "time_scale": "REAL NOT NULL DEFAULT 1",
            "duration_seconds": "REAL",
            "file_size": "INTEGER",
            "file_mtime_ns": "INTEGER",
            "updated_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in variant_columns:
                connection.execute(f"ALTER TABLE audio_variants ADD COLUMN {name} {declaration}")

        used: set[str] = set()
        sources = connection.execute(
            "SELECT id, audio_path, audio_stem, file_size, file_mtime_ns, created_at, updated_at, project_name FROM sources ORDER BY created_at, id"
        ).fetchall()
        for source in sources:
            base = validate_project_name(source["project_name"] or source["audio_stem"] or Path(source["audio_path"]).stem)
            name = base
            number = 2
            while name.casefold() in used:
                name = f"{base}-{number}"
                number += 1
            used.add(name.casefold())
            connection.execute("UPDATE sources SET project_name=? WHERE id=?", (name, source["id"]))
            exists = connection.execute(
                "SELECT 1 FROM audio_variants WHERE source_id=? AND audio_path=? COLLATE NOCASE",
                (source["id"], source["audio_path"]),
            ).fetchone()
            if not exists:
                connection.execute(
                    """INSERT INTO audio_variants(
                       id, source_id, name, audio_path, alignment_kind, created_at,
                       offset_seconds, time_scale, file_size, file_mtime_ns, updated_at
                       ) VALUES (?, ?, ?, ?, 'source_time', ?, 0, 1, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()), source["id"], Path(source["audio_path"]).stem,
                        source["audio_path"], source["created_at"], source["file_size"],
                        source["file_mtime_ns"], source["updated_at"],
                    ),
                )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_project_name ON sources(project_name COLLATE NOCASE)"
        )
        connection.execute("UPDATE schema_info SET version=2")

    @staticmethod
    def _upgrade_v2_to_v3(connection: sqlite3.Connection) -> None:
        connection.execute("DROP TABLE IF EXISTS source_speaker_mappings")
        connection.execute("DROP TABLE IF EXISTS global_speakers")
        variant_columns = {row["name"] for row in connection.execute("PRAGMA table_info(audio_variants)")}
        if "ordinal" not in variant_columns:
            connection.execute("ALTER TABLE audio_variants ADD COLUMN ordinal INTEGER NOT NULL DEFAULT 0")
            sources = connection.execute("SELECT id FROM sources").fetchall()
            for source in sources:
                rows = connection.execute(
                    "SELECT id FROM audio_variants WHERE source_id=? ORDER BY created_at, rowid",
                    (source["id"],),
                ).fetchall()
                for ordinal, row in enumerate(rows):
                    connection.execute(
                        "UPDATE audio_variants SET ordinal=? WHERE id=?", (ordinal, row["id"])
                    )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_tags (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (source_id, name)
            );
            CREATE TABLE IF NOT EXISTS assembly_items (
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                segment_id TEXT NOT NULL,
                selected_variant_id TEXT REFERENCES audio_variants(id) ON DELETE SET NULL,
                tag_id TEXT NOT NULL REFERENCES project_tags(id) ON DELETE RESTRICT,
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (source_id, segment_id)
            );
            """
        )
        now = _now()
        for source in connection.execute("SELECT id FROM sources").fetchall():
            exists = connection.execute(
                "SELECT 1 FROM project_tags WHERE source_id=? AND name='训练集'",
                (source["id"],),
            ).fetchone()
            if not exists:
                connection.execute(
                    "INSERT INTO project_tags(id, source_id, name, ordinal, created_at) VALUES (?, ?, '训练集', 0, ?)",
                    (str(uuid.uuid4()), source["id"], now),
                )
        connection.execute("UPDATE schema_info SET version=3")

    @staticmethod
    def _upgrade_v3_to_v4(connection: sqlite3.Connection) -> None:
        connection.execute("DROP TABLE IF EXISTS training_items")
        connection.execute("DROP TABLE IF EXISTS segment_candidates")
        connection.execute("UPDATE schema_info SET version=4")

    @staticmethod
    def _upgrade_v4_to_v5(connection: sqlite3.Connection) -> None:
        """Allow multiple projects to use the same source audio path."""
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE sources_v5 (
                    id TEXT PRIMARY KEY,
                    audio_path TEXT NOT NULL COLLATE NOCASE,
                    audio_name TEXT NOT NULL,
                    audio_stem TEXT NOT NULL,
                    file_size INTEGER,
                    file_mtime_ns INTEGER,
                    review_schema_version INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ui_preferences_json TEXT,
                    project_name TEXT NOT NULL COLLATE NOCASE
                );
                INSERT INTO sources_v5
                    SELECT id, audio_path, audio_name, audio_stem, file_size, file_mtime_ns,
                           review_schema_version, revision, created_at, updated_at,
                           ui_preferences_json, project_name
                    FROM sources;
                DROP TABLE sources;
                ALTER TABLE sources_v5 RENAME TO sources;
                CREATE UNIQUE INDEX idx_sources_project_name
                    ON sources(project_name COLLATE NOCASE);
                UPDATE schema_info SET version=5;
                COMMIT;
                """
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError(t("errors.foreign_key_upgrade"))

    @staticmethod
    def _upgrade_v5_to_v6(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE sources ADD COLUMN update_counter INTEGER NOT NULL DEFAULT 0")
        for table in ("sources", "segments", "audio_variants", "project_tags", "assembly_items"):
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})") if row[1] != "update_counter"]
            changed = " OR ".join(f'OLD."{column}" IS NOT NEW."{column}"' for column in columns)
            for event in ("INSERT", "UPDATE", "DELETE"):
                if table == "sources" and event != "UPDATE":
                    continue
                ref = "OLD" if event == "DELETE" else "NEW"
                source = f"{ref}.id" if table == "sources" else f"{ref}.source_id"
                condition = f" WHEN {changed}" if event == "UPDATE" else ""
                connection.execute(
                    f"CREATE TRIGGER counter_{table}_{event.lower()} AFTER {event} ON {table}{condition} "
                    f"BEGIN UPDATE sources SET update_counter=update_counter+1 WHERE id={source}; "
                    + ("UPDATE sources SET update_counter=update_counter+1 WHERE id=OLD.source_id AND OLD.source_id IS NOT NEW.source_id; " if event == "UPDATE" and table != "sources" else "")
                    + "END"
                )
        connection.execute("UPDATE schema_info SET version=6")

    @staticmethod
    def _upgrade_v6_to_v7(connection: sqlite3.Connection) -> None:
        """Store each item's tag as text, like its speaker, instead of a tag entity."""
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE assembly_items_v7 (
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    segment_id TEXT NOT NULL,
                    selected_variant_id TEXT REFERENCES audio_variants(id) ON DELETE SET NULL,
                    tag TEXT NOT NULL DEFAULT '训练集',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, segment_id)
                );
                INSERT INTO assembly_items_v7(
                    source_id, segment_id, selected_variant_id, tag, note, updated_at
                )
                SELECT a.source_id, a.segment_id, a.selected_variant_id,
                       CASE WHEN TRIM(COALESCE(t.name, '')) = '' THEN '训练集' ELSE TRIM(t.name) END,
                       a.note, a.updated_at
                FROM assembly_items a
                LEFT JOIN project_tags t ON t.id=a.tag_id;
                DROP TABLE assembly_items;
                DROP TABLE project_tags;
                ALTER TABLE assembly_items_v7 RENAME TO assembly_items;
                UPDATE schema_info SET version=7;
                COMMIT;
                """
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError(t("errors.foreign_key_upgrade"))

    @staticmethod
    def _upgrade_v7_to_v8(connection: sqlite3.Connection) -> None:
        """Change the default for future tag-less assembly rows without renaming saved tags."""
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE assembly_items_v8 (
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    segment_id TEXT NOT NULL,
                    selected_variant_id TEXT REFERENCES audio_variants(id) ON DELETE SET NULL,
                    tag TEXT NOT NULL DEFAULT '1训练集',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, segment_id)
                );
                INSERT INTO assembly_items_v8(
                    source_id, segment_id, selected_variant_id, tag, note, updated_at
                )
                SELECT source_id, segment_id, selected_variant_id, tag, note, updated_at
                FROM assembly_items;
                DROP TABLE assembly_items;
                ALTER TABLE assembly_items_v8 RENAME TO assembly_items;
                UPDATE schema_info SET version=8;
                COMMIT;
                """
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError(t("errors.foreign_key_upgrade"))

    @staticmethod
    def _upgrade_v8_to_v9(connection: sqlite3.Connection) -> None:
        """Use ``1`` for future tag-less rows without renaming saved tags."""
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE assembly_items_v9 (
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    segment_id TEXT NOT NULL,
                    selected_variant_id TEXT REFERENCES audio_variants(id) ON DELETE SET NULL,
                    tag TEXT NOT NULL DEFAULT '1',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, segment_id)
                );
                INSERT INTO assembly_items_v9(
                    source_id, segment_id, selected_variant_id, tag, note, updated_at
                )
                SELECT source_id, segment_id, selected_variant_id, tag, note, updated_at
                FROM assembly_items;
                DROP TABLE assembly_items;
                ALTER TABLE assembly_items_v9 RENAME TO assembly_items;
                UPDATE schema_info SET version=9;
                COMMIT;
                """
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError(t("errors.foreign_key_upgrade"))

    @staticmethod
    def _install_counter_triggers(connection: sqlite3.Connection) -> None:
        """Keep project counters aligned with the current persisted project tables."""
        legacy_tables = ("sources", "segments", "audio_variants", "project_tags", "assembly_items")
        for table in legacy_tables:
            for event in ("insert", "update", "delete"):
                connection.execute(f"DROP TRIGGER IF EXISTS counter_{table}_{event}")

        source_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(sources)")
            if row[1] not in {"update_counter", "ui_preferences_json"}
        ]
        changed = " OR ".join(f'OLD."{column}" IS NOT NEW."{column}"' for column in source_columns)
        connection.execute(
            f"CREATE TRIGGER counter_sources_update AFTER UPDATE ON sources WHEN {changed} "
            "BEGIN UPDATE sources SET update_counter=update_counter+1 WHERE id=NEW.id; END"
        )
        for table in ("segments", "audio_variants", "assembly_items"):
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            changed = " OR ".join(f'OLD."{column}" IS NOT NEW."{column}"' for column in columns)
            for event in ("insert", "update", "delete"):
                ref = "OLD" if event == "delete" else "NEW"
                condition = f" WHEN {changed}" if event == "update" else ""
                connection.execute(
                    f"CREATE TRIGGER counter_{table}_{event} AFTER {event.upper()} ON {table}{condition} "
                    f"BEGIN UPDATE sources SET update_counter=update_counter+1 WHERE id={ref}.source_id; "
                    + ("UPDATE sources SET update_counter=update_counter+1 WHERE id=OLD.source_id AND OLD.source_id IS NOT NEW.source_id; " if event == "update" else "")
                    + "END"
                )

    @staticmethod
    def _audio_key(audio: str | Path) -> str:
        return str(Path(audio).resolve())

    def has_project(self, project_name: str) -> bool:
        name = validate_project_name(project_name)
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM sources WHERE project_name=? COLLATE NOCASE", (name,)
            ).fetchone() is not None

    def project_update_counters(self, project_names: Iterable[str]) -> dict[str, str | None]:
        """Read only project counters; identity distinguishes deleted/recreated projects."""
        names = list(dict.fromkeys(validate_project_name(name) for name in project_names))
        if not names:
            return {}
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT project_name, id, update_counter FROM sources WHERE project_name COLLATE NOCASE IN ({','.join('?' for _ in names)})", names,
            ).fetchall()
        values = {row["project_name"].casefold(): f'{row["id"]}:{row["update_counter"]}' for row in rows}
        return {name: values.get(name.casefold()) for name in names}

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.id, s.project_name, s.revision, s.updated_at, COUNT(g.segment_id) AS segment_count
                   FROM sources s LEFT JOIN segments g ON g.source_id=s.id
                   GROUP BY s.id ORDER BY s.project_name COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_project(self, old_name: str, new_name: str) -> str:
        """Rename one project while retaining its stable source identity and relations."""
        old = validate_project_name(old_name)
        new = validate_project_name(new_name)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._find_source(connection, old)
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=old))
            conflict = connection.execute(
                "SELECT id FROM sources WHERE project_name=? COLLATE NOCASE", (new,)
            ).fetchone()
            if conflict and str(conflict["id"]) != str(source["id"]):
                raise FileExistsError(t("errors.project_exists", name=new))
            if new != str(source["project_name"]):
                connection.execute(
                    "UPDATE sources SET project_name=?, updated_at=? WHERE id=?",
                    (new, _now(), source["id"]),
                )
            connection.commit()
        return new

    @staticmethod
    def inspect_project_file(path: str | Path) -> dict[str, Any]:
        """Validate a portable export without modifying or attaching it."""
        source = Path(path).resolve()
        if source.suffix.lower() != PROJECT_DATABASE_SUFFIX:
            raise ValueError(t("errors.sqlite_only"))
        if not source.is_file():
            raise FileNotFoundError(source)
        try:
            connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                if not integrity or integrity[0] != "ok":
                    raise ValueError(t("errors.integrity"))
                objects = connection.execute(
                    "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
                versions = connection.execute("SELECT version FROM schema_info").fetchall()
                if len(versions) != 1 or int(versions[0]["version"]) not in {5, 6, 7, DATABASE_SCHEMA_VERSION}:
                    raise ValueError(t("errors.database_version"))
                schema_version = int(versions[0]["version"])
                tables = {str(row["name"]) for row in objects if row["type"] == "table"}
                expected_tables = PROJECT_DATABASE_TABLES | ({"project_tags"} if schema_version < 7 else set())
                if tables != expected_tables:
                    raise ValueError(t("errors.database_structure"))
                counter_tables = ("sources", "segments", "audio_variants", "assembly_items")
                if schema_version < 7:
                    counter_tables += ("project_tags",)
                counter_triggers = {f"counter_{table}_{event}" for table in counter_tables for event in ("insert", "update", "delete") if table != "sources" or event == "update"}
                if any(row["type"] == "view" or (row["type"] == "trigger" and row["name"] not in counter_triggers) for row in objects):
                    raise ValueError(t("errors.database_objects"))
                foreign_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
                if foreign_errors:
                    raise ValueError(t("errors.database_foreign_keys"))
                projects = connection.execute(
                    "SELECT id, project_name, revision FROM sources"
                ).fetchall()
                if len(projects) != 1:
                    raise ValueError(t("errors.single_project"))
                project = dict(projects[0])
                if project["project_name"] is None:
                    raise ValueError(t("errors.invalid_project_name"))
                project["project_name"] = validate_project_name(project["project_name"])
                project["segment_count"] = int(connection.execute(
                    "SELECT COUNT(*) FROM segments WHERE source_id=?", (project["id"],)
                ).fetchone()[0])
                project["schema_version"] = schema_version
                return project
            finally:
                connection.close()
        except sqlite3.DatabaseError as error:
            raise ValueError(t("errors.invalid_project_database", error=error)) from error

    def export_projects(
        self,
        project_names: Iterable[str],
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> list[Path]:
        directory = Path(destination).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        names = list(dict.fromkeys(validate_project_name(name) for name in project_names))
        if not names:
            raise ValueError(t("errors.select_export"))
        exported: list[Path] = []
        for name in names:
            with self._connection() as connection:
                source = self._find_source(connection, name)
                if not source:
                    raise FileNotFoundError(t("errors.project_not_found", name=name))
                source_id = str(source["id"])
                destination_path = directory / f"{name}{PROJECT_DATABASE_SUFFIX}"
                if destination_path == self.path:
                    raise ValueError(t("errors.export_same_database"))
                if destination_path.exists() and not overwrite:
                    raise FileExistsError(destination_path)
                temporary = directory / f".{name}.{uuid.uuid4().hex}.tmp"
                target = sqlite3.connect(temporary)
                try:
                    connection.backup(target)
                finally:
                    target.close()
            try:
                portable = sqlite3.connect(temporary)
                try:
                    portable.execute("PRAGMA foreign_keys = ON")
                    portable.execute("PRAGMA journal_mode = DELETE")
                    portable.execute("BEGIN IMMEDIATE")
                    portable.execute("DELETE FROM sources WHERE id<>?", (source_id,))
                    portable.commit()
                    portable.execute("VACUUM")
                finally:
                    portable.close()
                temporary.replace(destination_path)
                exported.append(destination_path)
            finally:
                temporary.unlink(missing_ok=True)
                Path(str(temporary) + "-wal").unlink(missing_ok=True)
                Path(str(temporary) + "-shm").unlink(missing_ok=True)
        return exported

    @staticmethod
    def _insert_row(
        connection: sqlite3.Connection,
        table: str,
        row: sqlite3.Row | dict[str, Any],
        **overrides: Any,
    ) -> None:
        values = dict(row)
        values.update(overrides)
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )

    def import_project_file(self, path: str | Path, *, replace: bool = False) -> str:
        source_path = Path(path).resolve()
        if source_path == self.path:
            raise ValueError(t("errors.import_self"))
        metadata = self.inspect_project_file(source_path)
        imported = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
        imported.row_factory = sqlite3.Row
        try:
            imported_source = imported.execute("SELECT * FROM sources").fetchone()
            project_name = str(metadata["project_name"])
            old_source_id = str(imported_source["id"])
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = self._find_source(connection, project_name)
                if existing and not replace:
                    raise FileExistsError(t("errors.project_exists", name=project_name))
                if existing:
                    connection.execute("DELETE FROM sources WHERE id=?", (existing["id"],))

                source_id = old_source_id
                if connection.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
                    source_id = str(uuid.uuid4())
                self._insert_row(
                    connection, "sources", imported_source, id=source_id,
                    update_counter=max(
                        int(existing["update_counter"]) if existing else 0,
                        int(dict(imported_source).get("update_counter", 0)),
                    ) + 1,
                    ui_preferences_json=None,
                )

                for row in imported.execute("SELECT * FROM segments WHERE source_id=?", (old_source_id,)):
                    self._insert_row(connection, "segments", row, source_id=source_id)
                for row in imported.execute("SELECT * FROM review_snapshots WHERE source_id=?", (old_source_id,)):
                    snapshot = json.loads(row["document_json"])
                    if isinstance(snapshot, dict):
                        snapshot.pop("ui_preferences", None)
                    self._insert_row(
                        connection, "review_snapshots", row, source_id=source_id,
                        document_json=json.dumps(snapshot, ensure_ascii=False),
                    )

                variant_ids: dict[str, str] = {}
                for row in imported.execute("SELECT * FROM audio_variants WHERE source_id=?", (old_source_id,)):
                    new_id = str(row["id"])
                    if connection.execute("SELECT 1 FROM audio_variants WHERE id=?", (new_id,)).fetchone():
                        new_id = str(uuid.uuid4())
                    self._insert_row(connection, "audio_variants", row, id=new_id, source_id=source_id)
                    variant_ids[str(row["id"])] = new_id

                legacy_tags = {}
                if int(metadata["schema_version"]) < 7:
                    legacy_tags = {
                        str(row["id"]): str(row["name"]).strip() or DEFAULT_TAG
                        for row in imported.execute(
                            "SELECT id, name FROM project_tags WHERE source_id=?", (old_source_id,)
                        )
                    }

                for row in imported.execute("SELECT * FROM assembly_items WHERE source_id=?", (old_source_id,)):
                    old_variant = row["selected_variant_id"]
                    tag = (
                        legacy_tags.get(str(row["tag_id"]), DEFAULT_TAG)
                        if int(metadata["schema_version"]) < 7
                        else str(row["tag"]).strip() or DEFAULT_TAG
                    )
                    connection.execute(
                        """INSERT INTO assembly_items(
                           source_id, segment_id, selected_variant_id, tag, note, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (source_id, row["segment_id"],
                         variant_ids.get(str(old_variant)) if old_variant else None,
                         tag, row["note"], row["updated_at"]),
                    )

                connection.commit()
            return project_name
        except sqlite3.IntegrityError as error:
            raise ValueError(t("errors.project_conflict", error=error)) from error
        finally:
            imported.close()

    def delete_projects(self, project_names: Iterable[str]) -> int:
        names = list(dict.fromkeys(validate_project_name(name) for name in project_names))
        if not names:
            raise ValueError(t("errors.select_delete"))
        output_directory = self.path.parent.resolve()
        workspaces: dict[str, Path] = {}
        for name in names:
            workspace = project_workspace_for(name, output_directory)
            resolved_workspace = workspace.resolve(strict=False)
            if resolved_workspace.parent != output_directory or resolved_workspace == output_directory:
                raise ValueError(t("errors.workspace_outside", path=workspace))
            workspaces[name] = workspace

        deleted_names: list[str] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for name in names:
                source = self._find_source(connection, name)
                if source:
                    connection.execute("DELETE FROM sources WHERE id=?", (source["id"],))
                    deleted_names.append(name)
            connection.commit()

        cleanup_errors: list[str] = []
        for name in deleted_names:
            workspace = workspaces[name]
            try:
                if workspace.is_symlink():
                    raise OSError(t("errors.workspace_symlink"))
                if workspace.exists():
                    if not workspace.is_dir():
                        raise OSError(t("errors.workspace_not_directory"))
                    shutil.rmtree(workspace)
            except OSError as error:
                cleanup_errors.append(f"{workspace}: {error}")
        if cleanup_errors:
            raise OSError(t("errors.cleanup_partial", count=len(deleted_names), details="\n".join(cleanup_errors)))
        return len(deleted_names)

    @staticmethod
    def _find_source(connection: sqlite3.Connection, key: str | Path) -> sqlite3.Row | None:
        text = str(key)
        source = connection.execute(
            "SELECT * FROM sources WHERE project_name=? COLLATE NOCASE", (text,)
        ).fetchone()
        if source:
            return source
        try:
            audio_key = str(Path(text).resolve())
        except (OSError, ValueError):
            return None
        matches = connection.execute(
            "SELECT * FROM sources WHERE audio_path=? COLLATE NOCASE", (audio_key,)
        ).fetchall()
        if len(matches) > 1:
            raise ValueError(t("errors.audio_multiple_projects"))
        return matches[0] if matches else None

    def project_name_for_audio(self, audio: str | Path) -> str:
        audio_key = self._audio_key(audio)
        with self._connection() as connection:
            sources = connection.execute(
                """SELECT DISTINCT s.project_name FROM sources s
                   LEFT JOIN audio_variants a ON a.source_id=s.id
                   WHERE a.audio_path=? COLLATE NOCASE OR s.audio_path=? COLLATE NOCASE
                   ORDER BY s.project_name COLLATE NOCASE""",
                (audio_key, audio_key),
            ).fetchall()
        if not sources:
            raise FileNotFoundError(t("errors.audio_unbound", audio=audio))
        if len(sources) > 1:
            raise ValueError(t(
                "errors.audio_multiple_named",
                names=", ".join(str(source["project_name"]) for source in sources),
            ))
        return str(sources[0]["project_name"])

    def create_project(self, project_name: str, audio: str | Path) -> dict[str, Any]:
        """Create an empty project and bind its initial audio without running models."""
        name = validate_project_name(project_name)
        if self.has_project(name):
            raise FileExistsError(t("errors.project_exists", name=name))
        document = build_review_document(audio, [])
        self.import_review(document, project_name=name)
        self.register_audio_asset(name, audio, name=Path(audio).stem)
        return self.load_review(name)

    def create_review(
        self,
        project_name: str,
        audio: str | Path,
        segments: Iterable[Segment],
    ) -> dict[str, Any]:
        project_name = validate_project_name(project_name)
        document = build_review_document(audio, segments)
        self.import_review(document, replace=True, project_name=project_name)
        asset = self.register_audio_asset(project_name, audio, name=Path(audio).stem)
        if document["segments"]:
            with self._connection() as connection:
                source = self._find_source(connection, project_name)
                assert source is not None
                now = _now()
                connection.executemany(
                    """INSERT INTO assembly_items(
                       source_id, segment_id, selected_variant_id, tag, note, updated_at
                       ) VALUES (?, ?, ?, ?, '', ?)
                       ON CONFLICT(source_id, segment_id) DO UPDATE SET
                       selected_variant_id=excluded.selected_variant_id, updated_at=excluded.updated_at""",
                    [
                        (source["id"], row["id"], asset["id"], DEFAULT_TAG, now)
                        for row in document["segments"]
                    ],
                )
                connection.commit()
        return document

    def import_review(
        self,
        document: dict[str, Any],
        *,
        replace: bool = False,
        project_name: str | None = None,
    ) -> str:
        candidate = json.loads(json.dumps(document, ensure_ascii=False))
        validate_review(candidate)
        audio_path = Path(candidate["audio_path"]).resolve() if candidate["audio_path"] else Path("")
        project_name = validate_project_name(project_name or audio_path.stem)
        candidate["audio_path"] = str(audio_path) if candidate["audio_path"] else ""
        stat = audio_path.stat() if audio_path.is_file() else None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id FROM sources WHERE project_name = ? COLLATE NOCASE",
                (project_name,),
            ).fetchone()
            if existing and not replace:
                raise ValueError(t("errors.project_exists", name=project_name))
            source_id = str(existing["id"]) if existing else str(uuid.uuid4())
            if existing:
                previous = self._load_review(connection, source_id)
                connection.execute(
                    "INSERT OR IGNORE INTO review_snapshots(source_id, revision, saved_at, document_json) VALUES (?, ?, ?, ?)",
                    (source_id, int(previous["revision"]), _now(), json.dumps(previous, ensure_ascii=False)),
                )
                connection.execute("DELETE FROM segments WHERE source_id = ?", (source_id,))
                connection.execute(
                    """UPDATE sources SET audio_path=?, audio_name=?, audio_stem=?, file_size=?, file_mtime_ns=?,
                       review_schema_version=?, revision=?, created_at=?, updated_at=?, ui_preferences_json=?
                       WHERE id=?""",
                    (candidate["audio_path"],) + self._source_values(candidate, audio_path, stat) + (source_id,),
                )
            else:
                connection.execute(
                    """INSERT INTO sources(
                       id, audio_path, audio_name, audio_stem, file_size, file_mtime_ns,
                       review_schema_version, revision, created_at, updated_at, ui_preferences_json, project_name
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source_id, candidate["audio_path"]) + self._source_values(candidate, audio_path, stat) + (project_name,),
                )
            self._insert_segments(connection, source_id, candidate["segments"])
            connection.commit()
        return source_id

    @staticmethod
    def _source_values(document: dict[str, Any], audio_path: Path, stat: Any) -> tuple[Any, ...]:
        return (
            audio_path.name,
            audio_path.stem,
            stat.st_size if stat else None,
            stat.st_mtime_ns if stat else None,
            int(document["schema_version"]),
            int(document["revision"]),
            str(document["created_at"]),
            str(document["updated_at"]),
            None,
        )

    @staticmethod
    def _insert_segments(connection: sqlite3.Connection, source_id: str, rows: list[dict[str, Any]]) -> None:
        connection.executemany(
            """INSERT INTO segments(
               source_id, segment_id, ordinal, start, end, speaker, text,
               deleted, manual_text, needs_asr, origin_ids_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    source_id,
                    str(row["id"]),
                    ordinal,
                    float(row["start"]),
                    float(row["end"]),
                    row.get("speaker"),
                    str(row.get("text", "")),
                    int(bool(row.get("deleted", False))),
                    int(bool(row.get("manual_text", False))),
                    int(bool(row.get("needs_asr", False))),
                    json.dumps(row.get("origin_ids", []), ensure_ascii=False),
                )
                for ordinal, row in enumerate(rows)
            ],
        )

    def load_review(self, project: str | Path) -> dict[str, Any]:
        with self._connection() as connection:
            source = self._find_source(connection, project)
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=project))
            return self._load_review(connection, str(source["id"]))

    @staticmethod
    def _load_review(connection: sqlite3.Connection, source_id: str) -> dict[str, Any]:
        source = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not source:
            raise FileNotFoundError(t("errors.source_not_found", id=source_id))
        rows = connection.execute(
            "SELECT * FROM segments WHERE source_id = ? ORDER BY ordinal",
            (source_id,),
        ).fetchall()
        document: dict[str, Any] = {
            "schema_version": int(source["review_schema_version"]),
            "revision": int(source["revision"]),
            "audio_path": str(source["audio_path"]),
            "created_at": str(source["created_at"]),
            "updated_at": str(source["updated_at"]),
            "segments": [
                {
                    "id": str(row["segment_id"]),
                    "start": float(row["start"]),
                    "end": float(row["end"]),
                    "speaker": row["speaker"],
                    "text": str(row["text"]),
                    "deleted": bool(row["deleted"]),
                    "manual_text": bool(row["manual_text"]),
                    "needs_asr": bool(row["needs_asr"]),
                    "origin_ids": json.loads(row["origin_ids_json"]),
                }
                for row in rows
            ],
        }
        validate_review(document)
        return document

    def save_review(
        self,
        project: str | Path,
        document: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._find_source(connection, project)
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=project))
            source_id = str(source["id"])
            current = self._load_review(connection, source_id)
            if expected_revision is not None and int(current["revision"]) != expected_revision:
                raise ValueError(t("errors.revision_conflict", expected=expected_revision, actual=current["revision"]))
            candidate = json.loads(json.dumps(document, ensure_ascii=False))
            candidate["schema_version"] = REVIEW_SCHEMA_VERSION
            candidate["revision"] = int(current["revision"]) + 1
            candidate["audio_path"] = current["audio_path"]
            candidate["created_at"] = current["created_at"]
            candidate["updated_at"] = _now()
            validate_review(candidate)
            if candidate["segments"] == current["segments"]:
                return current
            connection.execute(
                "INSERT OR IGNORE INTO review_snapshots(source_id, revision, saved_at, document_json) VALUES (?, ?, ?, ?)",
                (source_id, int(current["revision"]), _now(), json.dumps(current, ensure_ascii=False)),
            )
            connection.execute("DELETE FROM segments WHERE source_id = ?", (source_id,))
            connection.execute(
                """UPDATE sources SET revision=?, updated_at=?, ui_preferences_json=? WHERE id=?""",
                (
                    int(candidate["revision"]),
                    candidate["updated_at"],
                    None,
                    source_id,
                ),
            )
            self._insert_segments(connection, source_id, candidate["segments"])
            connection.commit()
        return candidate

    def register_audio_asset(
        self,
        project_name: str,
        audio: str | Path,
        *,
        name: str | None = None,
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        audio_path = Path(audio).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)
        stat = audio_path.stat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._find_source(connection, validate_project_name(project_name))
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=project_name))
            row = connection.execute(
                "SELECT * FROM audio_variants WHERE source_id=? AND audio_path=? COLLATE NOCASE",
                (source["id"], str(audio_path)),
            ).fetchone()
            if row:
                connection.execute(
                    """UPDATE audio_variants SET duration_seconds=COALESCE(?, duration_seconds),
                       file_size=?, file_mtime_ns=?, updated_at=? WHERE id=?""",
                    (duration_seconds, stat.st_size, stat.st_mtime_ns, _now(), row["id"]),
                )
            else:
                base = str(name or audio_path.stem).strip() or t("common.audio")
                asset_name = base
                number = 2
                while connection.execute(
                    "SELECT 1 FROM audio_variants WHERE source_id=? AND name=? COLLATE NOCASE",
                    (source["id"], asset_name),
                ).fetchone():
                    asset_name = f"{base}-{number}"
                    number += 1
                asset_id = str(uuid.uuid4())
                now = _now()
                ordinal = int(connection.execute(
                    "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM audio_variants WHERE source_id=?",
                    (source["id"],),
                ).fetchone()[0])
                connection.execute(
                    """INSERT INTO audio_variants(
                       id, source_id, name, audio_path, alignment_kind, created_at,
                       offset_seconds, time_scale, duration_seconds, file_size, file_mtime_ns, updated_at, ordinal
                       ) VALUES (?, ?, ?, ?, 'source_time', ?, 0, 1, ?, ?, ?, ?, ?)""",
                    (asset_id, source["id"], asset_name, str(audio_path), now, duration_seconds, stat.st_size, stat.st_mtime_ns, now, ordinal),
                )
            if not source["audio_path"]:
                connection.execute(
                    """UPDATE sources SET audio_path=?, audio_name=?, audio_stem=?, file_size=?,
                       file_mtime_ns=?, updated_at=? WHERE id=?""",
                    (str(audio_path), audio_path.name, audio_path.stem, stat.st_size, stat.st_mtime_ns, _now(), source["id"]),
                )
            connection.commit()
        return self.get_audio_asset(project_name, audio_path)

    def relocate_audio_asset(
        self, project_name: str, asset_id: str, audio: str | Path,
        *, duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Replace a binding's path without changing its identity or per-row choices."""
        audio_path = Path(audio).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)
        stat = audio_path.stat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._find_source(connection, validate_project_name(project_name))
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=project_name))
            asset = connection.execute(
                "SELECT * FROM audio_variants WHERE source_id=? AND id=?",
                (source["id"], str(asset_id)),
            ).fetchone()
            if not asset:
                raise FileNotFoundError(t("errors.project_audio_missing"))
            if connection.execute(
                "SELECT 1 FROM audio_variants WHERE source_id=? AND audio_path=? COLLATE NOCASE AND id<>?",
                (source["id"], str(audio_path), str(asset_id)),
            ).fetchone():
                raise ValueError(t("errors.audio_path_bound"))
            now = _now()
            connection.execute(
                """UPDATE audio_variants SET audio_path=?, duration_seconds=COALESCE(?, duration_seconds),
                   file_size=?, file_mtime_ns=?, updated_at=? WHERE id=?""",
                (str(audio_path), duration_seconds, stat.st_size, stat.st_mtime_ns, now, str(asset_id)),
            )
            # Keep WebUI1's primary source path in sync when relocating that binding.
            if str(source["audio_path"]).casefold() == str(asset["audio_path"]).casefold():
                connection.execute(
                    """UPDATE sources SET audio_path=?, audio_name=?, audio_stem=?, file_size=?,
                       file_mtime_ns=?, updated_at=? WHERE id=?""",
                    (str(audio_path), audio_path.name, audio_path.stem, stat.st_size, stat.st_mtime_ns, now, source["id"]),
                )
            connection.commit()
        return self.get_audio_asset_by_id(str(asset_id))

    def get_audio_asset(self, project_name: str, audio: str | Path) -> dict[str, Any]:
        audio_key = self._audio_key(audio)
        with self._connection() as connection:
            row = connection.execute(
                """SELECT a.* FROM audio_variants a JOIN sources s ON s.id=a.source_id
                   WHERE s.project_name=? COLLATE NOCASE AND a.audio_path=? COLLATE NOCASE""",
                (validate_project_name(project_name), audio_key),
            ).fetchone()
        if not row:
            raise FileNotFoundError(t("errors.project_audio_unbound", project=project_name, audio=audio))
        return dict(row)

    def get_audio_asset_by_id(self, asset_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT a.*, s.project_name FROM audio_variants a
                   JOIN sources s ON s.id=a.source_id WHERE a.id=?""",
                (str(asset_id),),
            ).fetchone()
        if not row:
            raise FileNotFoundError(t("errors.audio_missing"))
        return dict(row)

    def set_audio_offset(self, project_name: str, audio: str | Path, offset_seconds: float) -> dict[str, Any]:
        value = float(offset_seconds)
        if not -86400 <= value <= 86400:
            raise ValueError(t("errors.offset_range"))
        asset = self.get_audio_asset(project_name, audio)
        with self._connection() as connection:
            connection.execute(
                "UPDATE audio_variants SET offset_seconds=?, updated_at=? WHERE id=?",
                (value, _now(), asset["id"]),
            )
            connection.commit()
        return self.get_audio_asset(project_name, audio)

    def list_audio_assets(self, project_name: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            source = self._find_source(connection, validate_project_name(project_name))
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=project_name))
            rows = connection.execute(
                "SELECT * FROM audio_variants WHERE source_id=? ORDER BY ordinal, created_at, id",
                (source["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_assembly(self, project_names: Iterable[str]) -> dict[str, Any]:
        names = list(dict.fromkeys(validate_project_name(name) for name in project_names))
        projects: list[dict[str, Any]] = []
        with self._connection() as connection:
            for name in names:
                source = self._find_source(connection, name)
                if not source:
                    raise FileNotFoundError(t("errors.project_not_found", name=name))
                source_id = str(source["id"])
                variants = [dict(row) for row in connection.execute(
                    "SELECT * FROM audio_variants WHERE source_id=? ORDER BY ordinal, created_at, id",
                    (source_id,),
                )]
                first_variant_id = variants[0]["id"] if variants else None
                choices = {
                    str(row["segment_id"]): dict(row)
                    for row in connection.execute(
                        """SELECT segment_id, selected_variant_id, note, tag
                           FROM assembly_items WHERE source_id=?""",
                        (source_id,),
                    )
                }
                segments = []
                for row in connection.execute(
                    "SELECT * FROM segments WHERE source_id=? AND deleted=0 ORDER BY start, end, ordinal",
                    (source_id,),
                ):
                    choice = choices.get(str(row["segment_id"]))
                    selected_variant = (
                        choice.get("selected_variant_id") if choice is not None else first_variant_id
                    )
                    if selected_variant and not any(asset["id"] == selected_variant for asset in variants):
                        selected_variant = first_variant_id
                    segments.append({
                        "id": str(row["segment_id"]),
                        "start": float(row["start"]),
                        "end": float(row["end"]),
                        "duration": float(row["end"]) - float(row["start"]),
                        "speaker": row["speaker"] or "Unassigned",
                        "text": str(row["text"]),
                        "tag": str((choice or {}).get("tag") or DEFAULT_TAG),
                        "note": str((choice or {}).get("note") or ""),
                        "selected_variant_id": selected_variant,
                    })
                tags = sorted({row["tag"] for row in segments}) or [DEFAULT_TAG]
                projects.append({
                    "id": source_id,
                    "project_name": str(source["project_name"]),
                    "revision": int(source["revision"]),
                    "tags": tags,
                    "variants": variants,
                    "segments": segments,
                })
        return {"projects": projects}

    def delete_audio_asset(self, project_name: str, asset_id: str) -> None:
        """Delete one project audio path while preserving affected rows as unassigned."""
        name = validate_project_name(project_name)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._find_source(connection, name)
            if not source:
                raise FileNotFoundError(t("errors.project_not_found", name=name))
            source_id = str(source["id"])
            asset = connection.execute(
                "SELECT id FROM audio_variants WHERE id=? AND source_id=?",
                (str(asset_id), source_id),
            ).fetchone()
            if not asset:
                raise FileNotFoundError(t("errors.project_audio_missing"))

            first = connection.execute(
                "SELECT id FROM audio_variants WHERE source_id=? ORDER BY ordinal, created_at, id LIMIT 1",
                (source_id,),
            ).fetchone()
            if first and str(first["id"]) == str(asset_id):
                now = _now()
                connection.execute(
                    """INSERT INTO assembly_items(
                       source_id, segment_id, selected_variant_id, tag, note, updated_at
                       )
                       SELECT ?, s.segment_id, ?, '1', '', ? FROM segments s
                       WHERE s.source_id=? AND s.deleted=0
                         AND NOT EXISTS (
                           SELECT 1 FROM assembly_items a
                           WHERE a.source_id=s.source_id AND a.segment_id=s.segment_id
                         )""",
                    (source_id, str(asset_id), now, source_id),
                )
            connection.execute(
                "DELETE FROM audio_variants WHERE id=? AND source_id=?",
                (str(asset_id), source_id),
            )
            connection.commit()

    def save_assembly(self, projects: Iterable[dict[str, Any]]) -> dict[str, int]:
        payloads = list(projects)
        revisions: dict[str, int] = {}
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            resolved: list[tuple[dict[str, Any], sqlite3.Row]] = []
            for payload in payloads:
                name = validate_project_name(payload.get("project_name", ""))
                source = self._find_source(connection, name)
                if not source:
                    raise FileNotFoundError(t("errors.project_not_found", name=name))
                expected = int(payload.get("revision", 0))
                if int(source["revision"]) != expected:
                    raise ValueError(t("errors.stale_project", name=name))
                resolved.append((payload, source))

            for payload, source in resolved:
                name = str(source["project_name"])
                source_id = str(source["id"])
                variant_rows = {
                    str(row["id"]): dict(row)
                    for row in connection.execute(
                        "SELECT * FROM audio_variants WHERE source_id=?", (source_id,)
                    )
                }
                variant_ids = set(variant_rows)
                raw_deleted_audio_ids = payload.get("deleted_audio_ids") or []
                if not isinstance(raw_deleted_audio_ids, list):
                    raise ValueError(t("errors.invalid_delete_list", name=name))
                deleted_audio_ids = {str(value) for value in raw_deleted_audio_ids}
                if not deleted_audio_ids.issubset(variant_ids):
                    raise ValueError(t("errors.invalid_delete_audio", name=name))
                if deleted_audio_ids:
                    placeholders = ",".join("?" for _ in deleted_audio_ids)
                    connection.execute(
                        f"DELETE FROM audio_variants WHERE source_id=? AND id IN ({placeholders})",
                        (source_id, *deleted_audio_ids),
                    )
                    variant_ids -= deleted_audio_ids

                relocated_audio = payload.get("relocated_audio") or []
                if not isinstance(relocated_audio, list) or any(not isinstance(item, dict) for item in relocated_audio):
                    raise ValueError(t("errors.invalid_relocate_list", name=name))
                for item in relocated_audio:
                    variant_id = str(item.get("id", ""))
                    if variant_id not in variant_ids:
                        raise ValueError(t("errors.invalid_relocate_audio", name=name))
                    audio_path = Path(str(item.get("audio_path", ""))).resolve()
                    if not audio_path.is_file():
                        raise FileNotFoundError(audio_path)
                    if connection.execute(
                        "SELECT 1 FROM audio_variants WHERE source_id=? AND audio_path=? COLLATE NOCASE AND id<>?",
                        (source_id, str(audio_path), variant_id),
                    ).fetchone():
                        raise ValueError(t("errors.duplicate_audio_path", name=name))
                    stat = audio_path.stat()
                    duration = item.get("duration_seconds")
                    connection.execute(
                        """UPDATE audio_variants SET audio_path=?, duration_seconds=COALESCE(?, duration_seconds),
                           file_size=?, file_mtime_ns=?, updated_at=? WHERE source_id=? AND id=?""",
                        (str(audio_path), float(duration) if duration is not None else None,
                         stat.st_size, stat.st_mtime_ns, _now(), source_id, variant_id),
                    )
                    if str(source["audio_path"]).casefold() == str(variant_rows[variant_id]["audio_path"]).casefold():
                        connection.execute(
                            """UPDATE sources SET audio_path=?, audio_name=?, audio_stem=?, file_size=?,
                               file_mtime_ns=?, updated_at=? WHERE id=?""",
                            (str(audio_path), audio_path.name, audio_path.stem, stat.st_size,
                             stat.st_mtime_ns, _now(), source_id),
                        )

                added_audio = payload.get("added_audio") or []
                if not isinstance(added_audio, list) or any(not isinstance(item, dict) for item in added_audio):
                    raise ValueError(t("errors.invalid_add_list", name=name))
                pending_map: dict[str, str] = {}
                for item in added_audio:
                    pending_id = str(item.get("id", ""))
                    if not pending_id.startswith("pending:") or pending_id in pending_map:
                        raise ValueError(t("errors.invalid_add_audio", name=name))
                    audio_path = Path(str(item.get("audio_path", ""))).resolve()
                    if not audio_path.is_file():
                        raise FileNotFoundError(audio_path)
                    if connection.execute(
                        "SELECT 1 FROM audio_variants WHERE source_id=? AND audio_path=? COLLATE NOCASE",
                        (source_id, str(audio_path)),
                    ).fetchone():
                        raise ValueError(t("errors.duplicate_audio_path", name=name))
                    base = str(item.get("name") or audio_path.stem).strip() or t("common.audio")
                    asset_name, number = base, 2
                    while connection.execute(
                        "SELECT 1 FROM audio_variants WHERE source_id=? AND name=? COLLATE NOCASE",
                        (source_id, asset_name),
                    ).fetchone():
                        asset_name = f"{base}-{number}"
                        number += 1
                    asset_id, now, stat = str(uuid.uuid4()), _now(), audio_path.stat()
                    ordinal = int(connection.execute(
                        "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM audio_variants WHERE source_id=?",
                        (source_id,),
                    ).fetchone()[0])
                    duration = item.get("duration_seconds")
                    connection.execute(
                        """INSERT INTO audio_variants(
                           id, source_id, name, audio_path, alignment_kind, created_at,
                           offset_seconds, time_scale, duration_seconds, file_size, file_mtime_ns, updated_at, ordinal
                           ) VALUES (?, ?, ?, ?, 'source_time', ?, 0, 1, ?, ?, ?, ?, ?)""",
                        (asset_id, source_id, asset_name, str(audio_path), now,
                         float(duration) if duration is not None else None,
                         stat.st_size, stat.st_mtime_ns, now, ordinal),
                    )
                    pending_map[pending_id] = asset_id
                    variant_ids.add(asset_id)

                current_source_path = str(connection.execute(
                    "SELECT audio_path FROM sources WHERE id=?", (source_id,)
                ).fetchone()[0] or "")
                primary_exists = current_source_path and connection.execute(
                    "SELECT 1 FROM audio_variants WHERE source_id=? AND audio_path=? COLLATE NOCASE",
                    (source_id, current_source_path),
                ).fetchone()
                if not primary_exists:
                    primary = connection.execute(
                        "SELECT * FROM audio_variants WHERE source_id=? ORDER BY ordinal, created_at, id LIMIT 1",
                        (source_id,),
                    ).fetchone()
                    connection.execute(
                        """UPDATE sources SET audio_path=?, audio_name=?, audio_stem=?, file_size=?,
                           file_mtime_ns=?, updated_at=? WHERE id=?""",
                        ((str(primary["audio_path"]) if primary else ""),
                         (Path(str(primary["audio_path"])).name if primary else ""),
                         (Path(str(primary["audio_path"])).stem if primary else ""),
                         (primary["file_size"] if primary else None),
                         (primary["file_mtime_ns"] if primary else None), _now(), source_id),
                    )
                offsets = payload.get("offsets") or {}
                for variant_id, raw_offset in offsets.items():
                    resolved_variant_id = pending_map.get(str(variant_id), str(variant_id))
                    if resolved_variant_id not in variant_ids:
                        raise ValueError(t("errors.invalid_audio_variant", name=name))
                    offset = float(raw_offset)
                    if not -86400 <= offset <= 86400:
                        raise ValueError(t("errors.offset_range"))
                    connection.execute(
                        "UPDATE audio_variants SET offset_seconds=?, updated_at=? WHERE id=?",
                        (offset, _now(), resolved_variant_id),
                    )

                current = self._load_review(connection, source_id)
                current_rows = {str(row["id"]): row for row in current["segments"] if not row.get("deleted")}
                items = list(payload.get("items") or [])
                supplied_ids = {str(item.get("id", "")) for item in items}
                if supplied_ids != set(current_rows):
                    raise ValueError(t("errors.stale_items", name=name))
                review_changed = False
                for item in items:
                    segment_id = str(item["id"])
                    text = str(item.get("text", ""))
                    if text != str(current_rows[segment_id]["text"]):
                        review_changed = True
                        connection.execute(
                            "UPDATE segments SET text=?, manual_text=1 WHERE source_id=? AND segment_id=?",
                            (text, source_id, segment_id),
                        )
                    speaker = str(item.get("speaker", current_rows[segment_id]["speaker"])).strip()
                    if not speaker or len(speaker) > 100:
                        raise ValueError(t("errors.invalid_speaker", name=name))
                    if speaker != str(current_rows[segment_id]["speaker"]):
                        review_changed = True
                        connection.execute(
                            "UPDATE segments SET speaker=? WHERE source_id=? AND segment_id=?",
                            (speaker, source_id, segment_id),
                        )
                    tag_name = str(item.get("tag") or DEFAULT_TAG).strip()
                    if not tag_name or len(tag_name) > 100:
                        raise ValueError(t("errors.invalid_tag", name=name))
                    note = str(item.get("note", ""))
                    if len(note) > 10000:
                        raise ValueError(t("errors.note_too_long"))
                    variant_id = item.get("selected_variant_id")
                    if variant_id is not None:
                        variant_id = pending_map.get(str(variant_id), str(variant_id))
                    if variant_id is not None and str(variant_id) not in variant_ids:
                        raise ValueError(t("errors.invalid_audio_variant", name=name))
                    connection.execute(
                        """INSERT INTO assembly_items(
                           source_id, segment_id, selected_variant_id, tag, note, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(source_id, segment_id) DO UPDATE SET
                           selected_variant_id=excluded.selected_variant_id,
                           tag=excluded.tag, note=excluded.note, updated_at=excluded.updated_at""",
                        (source_id, segment_id, variant_id, tag_name, note, _now()),
                    )
                if review_changed:
                    connection.execute(
                        "INSERT OR IGNORE INTO review_snapshots(source_id, revision, saved_at, document_json) VALUES (?, ?, ?, ?)",
                        (source_id, int(source["revision"]), _now(), json.dumps(current, ensure_ascii=False)),
                    )
                    new_revision = int(source["revision"]) + 1
                    connection.execute(
                        "UPDATE sources SET revision=?, updated_at=? WHERE id=?",
                        (new_revision, _now(), source_id),
                    )
                else:
                    new_revision = int(source["revision"])
                revisions[name] = new_revision
            connection.commit()
        return revisions

    def snapshot_count(self, audio: str | Path) -> int:
        with self._connection() as connection:
            row = connection.execute(
                """SELECT COUNT(*) FROM review_snapshots r JOIN sources s ON s.id=r.source_id
                   WHERE s.audio_path = ? COLLATE NOCASE""",
                (self._audio_key(audio),),
            ).fetchone()
            return int(row[0])
