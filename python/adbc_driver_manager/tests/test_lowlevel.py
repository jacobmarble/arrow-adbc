# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import pyarrow
import pytest

import adbc_driver_manager


@pytest.fixture
def sqlite():
    """Dynamically load the SQLite driver."""
    with adbc_driver_manager.AdbcDatabase(driver="adbc_driver_sqlite") as db:
        with adbc_driver_manager.AdbcConnection(db) as conn:
            yield (db, conn)


def _import(handle):
    """Helper to import a C Data Interface handle."""
    if isinstance(handle, adbc_driver_manager.ArrowArrayStreamHandle):
        return pyarrow.RecordBatchReader._import_from_c(handle.address)
    elif isinstance(handle, adbc_driver_manager.ArrowSchemaHandle):
        return pyarrow.Schema._import_from_c(handle.address)
    raise NotImplementedError(f"Importing {handle!r}")


def _bind(stmt, batch):
    array = adbc_driver_manager.ArrowArrayHandle()
    schema = adbc_driver_manager.ArrowSchemaHandle()
    batch._export_to_c(array.address, schema.address)
    stmt.bind(array, schema)


def test_version():
    assert adbc_driver_manager.__version__


def test_database_init():
    with pytest.raises(
        adbc_driver_manager.ProgrammingError,
        match=".*Must provide 'driver' parameter.*",
    ):
        with adbc_driver_manager.AdbcDatabase():
            pass


@pytest.mark.sqlite
def test_connection_get_info(sqlite):
    _, conn = sqlite
    codes = [
        adbc_driver_manager.AdbcInfoCode.VENDOR_NAME,
        adbc_driver_manager.AdbcInfoCode.VENDOR_VERSION.value,
        adbc_driver_manager.AdbcInfoCode.DRIVER_NAME,
        adbc_driver_manager.AdbcInfoCode.DRIVER_VERSION.value,
        adbc_driver_manager.AdbcInfoCode.DRIVER_ARROW_VERSION.value,
    ]
    handle = conn.get_info()
    table = _import(handle).read_all()
    assert table.num_rows > 0
    data = dict(zip(table[0].to_pylist(), table[1].to_pylist()))
    for code in codes:
        assert code in data
        assert data[code]

    handle = conn.get_info()
    table = _import(handle).read_all()
    assert table.num_rows > 0
    assert set(codes) == set(table[0].to_pylist())


@pytest.mark.sqlite
def test_connection_get_objects(sqlite):
    _, conn = sqlite
    data = pyarrow.record_batch(
        [
            [1, 2, 3, 4],
            ["a", "b", "c", "d"],
        ],
        names=["ints", "strs"],
    )
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_options(**{adbc_driver_manager.INGEST_OPTION_TARGET_TABLE: "foo"})
        _bind(stmt, data)
        stmt.execute_update()

    handle = conn.get_objects(adbc_driver_manager.GetObjectsDepth.ALL)
    table = _import(handle).read_all()

    db_schemas = pyarrow.concat_arrays(table[1].chunks).flatten()
    tables = db_schemas.flatten()[1].flatten()
    table_names, _, columns, *_ = tables.flatten()
    columns = columns.flatten()
    column_names = columns.flatten()[0]

    assert "foo" in table_names.to_pylist()
    assert "ints" in column_names.to_pylist()
    assert "strs" in column_names.to_pylist()


@pytest.mark.sqlite
def test_connection_get_table_schema(sqlite):
    _, conn = sqlite
    data = pyarrow.record_batch(
        [
            [1, 2, 3, 4],
            ["a", "b", "c", "d"],
        ],
        names=["ints", "strs"],
    )
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_options(**{adbc_driver_manager.INGEST_OPTION_TARGET_TABLE: "foo"})
        _bind(stmt, data)
        stmt.execute_update()

    handle = conn.get_table_schema(catalog=None, db_schema=None, table_name="foo")
    assert data.schema == _import(handle)


@pytest.mark.sqlite
def test_connection_get_table_types(sqlite):
    _, conn = sqlite
    handle = conn.get_table_types()
    table = _import(handle).read_all()
    assert "table" in table[0].to_pylist()


@pytest.mark.sqlite
def test_query(sqlite):
    _, conn = sqlite
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_sql_query("SELECT 1")
        handle, _ = stmt.execute_query()
        table = _import(handle).read_all()
        assert table == pyarrow.table([[1]], names=["1"])


@pytest.mark.sqlite
def test_prepared(sqlite):
    _, conn = sqlite
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_sql_query("SELECT ?")
        stmt.prepare()

        _bind(stmt, pyarrow.record_batch([[1, 2, 3, 4]], names=["1"]))
        handle, _ = stmt.execute_query()
        table = _import(handle).read_all()
        assert table == pyarrow.table([[1, 2, 3, 4]], names=["?"])


@pytest.mark.sqlite
def test_ingest(sqlite):
    _, conn = sqlite
    data = pyarrow.record_batch(
        [
            [1, 2, 3, 4],
            ["a", "b", "c", "d"],
        ],
        names=["ints", "strs"],
    )
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_options(**{adbc_driver_manager.INGEST_OPTION_TARGET_TABLE: "foo"})
        _bind(stmt, data)
        stmt.execute_update()

        stmt.set_sql_query("SELECT * FROM foo")
        handle, _ = stmt.execute_query()
        table = _import(handle).read_all()
        assert table == pyarrow.Table.from_batches([data])


@pytest.mark.sqlite
def test_autocommit(sqlite):
    _, conn = sqlite

    # Autocommit enabled by default
    with pytest.raises(adbc_driver_manager.ProgrammingError) as errholder:
        conn.commit()
    assert (
        errholder.value.status_code == adbc_driver_manager.AdbcStatusCode.INVALID_STATE
    )

    with pytest.raises(adbc_driver_manager.ProgrammingError) as errholder:
        conn.rollback()
    assert (
        errholder.value.status_code == adbc_driver_manager.AdbcStatusCode.INVALID_STATE
    )

    conn.set_autocommit(True)

    conn.set_autocommit(False)

    # Test rollback
    data = pyarrow.record_batch(
        [
            [1, 2, 3, 4],
            ["a", "b", "c", "d"],
        ],
        names=["ints", "strs"],
    )
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_options(**{adbc_driver_manager.INGEST_OPTION_TARGET_TABLE: "foo"})
        _bind(stmt, data)
        stmt.execute_update()

        stmt.set_sql_query("SELECT * FROM foo")
        handle, _ = stmt.execute_query()
        table = _import(handle).read_all()
        assert table == pyarrow.Table.from_batches([data])

    conn.rollback()

    # Data should not be readable
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        with pytest.raises(adbc_driver_manager.Error):
            stmt.set_sql_query("SELECT * FROM foo")
            stmt.execute_query()

    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_options(**{adbc_driver_manager.INGEST_OPTION_TARGET_TABLE: "foo"})
        _bind(stmt, data)
        stmt.execute_update()

    # Enabling autocommit should implicitly commit
    conn.set_autocommit(True)
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_sql_query("SELECT * FROM foo")
        handle, _ = stmt.execute_query()
        table = _import(handle).read_all()

    conn.set_autocommit(False)
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_options(**{adbc_driver_manager.INGEST_OPTION_TARGET_TABLE: "bar"})
        _bind(stmt, data)
        stmt.execute_update()

    # Explicit commit
    conn.commit()
    with adbc_driver_manager.AdbcStatement(conn) as stmt:
        stmt.set_sql_query("SELECT * FROM foo")
        handle, _ = stmt.execute_query()
        table = _import(handle).read_all()
        assert table == pyarrow.Table.from_batches([data])


@pytest.mark.sqlite
def test_child_tracking(sqlite):
    with adbc_driver_manager.AdbcDatabase(driver="adbc_driver_sqlite") as db:
        with adbc_driver_manager.AdbcConnection(db) as conn:
            with adbc_driver_manager.AdbcStatement(conn):
                with pytest.raises(
                    RuntimeError,
                    match="Cannot close AdbcDatabase with open AdbcConnection",
                ):
                    db.close()
                with pytest.raises(
                    RuntimeError,
                    match="Cannot close AdbcConnection with open AdbcStatement",
                ):
                    conn.close()
            with pytest.raises(
                RuntimeError, match="Cannot close AdbcDatabase with open AdbcConnection"
            ):
                db.close()
