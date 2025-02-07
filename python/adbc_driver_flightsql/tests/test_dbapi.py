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


def test_query_trivial(dremio_dbapi):
    with dremio_dbapi.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


def test_query_partitioned(dremio_dbapi):
    with dremio_dbapi.cursor() as cur:
        partitions, schema = cur.adbc_execute_partitions("SELECT 1")
        assert len(partitions) == 1
        assert schema.equals(pyarrow.schema([("EXPR$0", "int32")]))

        cur.adbc_read_partition(partitions[0])
        assert cur.fetchone() == (1,)
