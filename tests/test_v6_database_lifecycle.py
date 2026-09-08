"""Connection closure waits for the complete SQLite operation lifecycle."""

import threading
import zipfile

import pytest

from electrochem_v6.store.database import Database


@pytest.mark.parametrize("operation", ["read", "transaction", "transaction_connection_selection"])
def test_close_all_waits_for_active_connection_use(tmp_path, monkeypatch, operation):
    database = Database(str(tmp_path / "lifecycle.db"))
    in_operation = threading.Event()
    release_operation = threading.Event()
    close_attempted = threading.Event()
    closed = threading.Event()
    errors = []
    values = []
    original_get_conn = database._get_conn

    if operation == "transaction_connection_selection":
        def select_connection():
            connection = original_get_conn()
            in_operation.set()
            assert release_operation.wait(10)
            return connection

        monkeypatch.setattr(database, "_get_conn", select_connection)

    def use_connection():
        try:
            context = database.read if operation == "read" else database.transaction
            with context() as connection:
                if operation != "transaction_connection_selection":
                    connection.execute("SELECT 1").fetchone()
                    in_operation.set()
                    assert release_operation.wait(10)
                values.append(connection.execute("SELECT 42").fetchone()[0])
        except Exception as exc:
            errors.append(exc)

    def close_connections():
        close_attempted.set()
        database.close_all()
        closed.set()

    worker = threading.Thread(target=use_connection)
    closer = threading.Thread(target=close_connections)
    worker.start()
    try:
        assert in_operation.wait(10)
        closer.start()
        assert close_attempted.wait(10)
        # The worker is paused in Python, not inside native SQLite. Even an
        # unfixed implementation fails safely instead of racing sqlite3_close.
        assert not closed.wait(0.2), "close_all closed a connection still in use"
    finally:
        release_operation.set()
        worker.join(10)
        if closer.ident is not None:
            closer.join(10)
    assert not worker.is_alive() and not closer.is_alive()
    assert errors == []
    assert values == [42]
    assert closed.is_set()
    assert database._connections == set()


def test_connection_validation_cannot_overlap_close_all(tmp_path):
    database = Database(str(tmp_path / "validation.db"))
    validating = threading.Event()
    resume = threading.Event()
    close_attempted = threading.Event()
    closed = threading.Event()
    errors = []

    class PausedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql):
            validating.set()
            assert resume.wait(10)
            return self.connection.execute(sql)

        def close(self):
            self.connection.close()

    def validate():
        try:
            connection = database._get_conn()
            proxy = PausedConnection(connection)
            with database._lock:
                database._connections.discard(connection)
                database._connections.add(proxy)
                database._local.conn = proxy
            # Pause immediately before the native SELECT 1 that crashed CI.
            assert database._get_conn() is proxy
        except Exception as exc:
            errors.append(exc)

    def close():
        close_attempted.set()
        database.close_all()
        closed.set()

    worker = threading.Thread(target=validate)
    closer = threading.Thread(target=close)
    worker.start()
    try:
        assert validating.wait(10)
        closer.start()
        assert close_attempted.wait(10)
        assert not closed.wait(0.2), "connection validation overlapped close_all"
    finally:
        resume.set()
        worker.join(10)
        if closer.ident is not None:
            closer.join(10)
    assert not worker.is_alive() and not closer.is_alive()
    assert errors == []
    assert closed.is_set()


def test_worker_reopens_connection_after_close_all(tmp_path):
    database = Database(str(tmp_path / "reopen.db"))
    first_read = threading.Event()
    closed = threading.Event()
    connections = []
    errors = []

    def read_twice():
        try:
            with database.read() as connection:
                connections.append(connection)
                assert connection.execute("SELECT 7").fetchone()[0] == 7
            first_read.set()
            assert closed.wait(10)
            with database.read() as connection:
                connections.append(connection)
                assert connection.execute("SELECT 8").fetchone()[0] == 8
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=read_twice)
    worker.start()
    try:
        assert first_read.wait(10)
        database.close_all()
    finally:
        closed.set()
        worker.join(10)
        database.close_all()
    assert not worker.is_alive()
    assert errors == []
    assert len(connections) == 2 and connections[0] is not connections[1]


def test_paused_zip_consumer_does_not_hold_database_lock(tmp_path, monkeypatch):
    from electrochem_v6.core.project_archive import write_project_archive

    database = Database(str(tmp_path / "archive.db"))
    source = tmp_path / "source.txt"
    source.write_text("synthetic CV source", encoding="utf-8")
    database.add_history_record({
        "type": "CV", "sample_name": "archive sample", "project_id": "archive-project",
        "run_id": "archive-run", "timestamp": "2026-09-09 10:00:00",
        "file_path": str(source), "folder_path": str(tmp_path),
    })
    writing_zip = threading.Event()
    resume_zip = threading.Event()
    database_work_done = threading.Event()
    errors = []
    summaries = []
    original_write = zipfile.ZipFile.write
    archive_path = tmp_path / "export.zip"

    def paused_write(archive, *args, **kwargs):
        writing_zip.set()
        assert resume_zip.wait(20)
        return original_write(archive, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", paused_write)

    def export():
        try:
            summaries.append(write_project_archive(
                database.iter_history_archive_records(project_id="archive-project", batch_size=1),
                archive_path,
                application_roots=[tmp_path],
            ))
        except Exception as exc:
            errors.append(exc)

    def read_and_write_database():
        try:
            with database.transaction() as connection:
                connection.execute("INSERT INTO meta(key,value) VALUES ('concurrent-progress','done')")
            with database.read() as connection:
                row = connection.execute("SELECT value FROM meta WHERE key='concurrent-progress'").fetchone()
                assert row[0] == "done"
            database_work_done.set()
        except Exception as exc:
            errors.append(exc)

    exporter = threading.Thread(target=export)
    database_worker = threading.Thread(target=read_and_write_database)
    exporter.start()
    try:
        assert writing_zip.wait(10)
        database_worker.start()
        assert database_work_done.wait(10), "ZIP consumer retained the database connection lock"
        assert exporter.is_alive(), "ZIP pause must cover the concurrent database operations"
    finally:
        resume_zip.set()
        exporter.join(10)
        if database_worker.ident is not None:
            database_worker.join(10)
        database.close_all()
    assert not exporter.is_alive() and not database_worker.is_alive()
    assert errors == []
    assert len(summaries) == 1 and summaries[0].file_count == 1
    with zipfile.ZipFile(archive_path) as archive:
        source_name = next(name for name in archive.namelist() if name.endswith("/source/source.txt"))
        assert archive.read(source_name) == source.read_bytes()


def test_archive_batches_keep_selected_order_without_new_or_duplicate_records(tmp_path):
    database = Database(str(tmp_path / "archive-order.db"))
    for name, timestamp in (("A", "2026-09-03"), ("B", "2026-09-02"), ("C", "2026-09-01")):
        database.add_history_record({
            "type": "CV", "sample_name": name, "project_id": "archive-project",
            "run_id": name, "timestamp": timestamp, "file_path": f"{name}.txt",
        })
    records = database.iter_history_archive_records(project_id="archive-project", batch_size=1)
    try:
        assert next(records)["sample_name"] == "A"
        with database.transaction() as connection:
            connection.execute("DELETE FROM history_records WHERE sample_name='B'")
            connection.execute("UPDATE history_records SET timestamp='2026-09-04' WHERE sample_name='C'")
            connection.execute("UPDATE history_records SET timestamp='2026-08-01' WHERE sample_name='A'")
        database.add_history_record({
            "type": "CV", "sample_name": "D", "project_id": "archive-project",
            "run_id": "D", "timestamp": "2026-09-05", "file_path": "D.txt",
        })
        # Also exercise the absence of a live cursor between metadata batches.
        database.close_all()
        assert [record["sample_name"] for record in records] == ["C"]
    finally:
        records.close()
        database.close_all()
