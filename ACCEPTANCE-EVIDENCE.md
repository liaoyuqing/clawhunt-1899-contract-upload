# 验收证据对照表（AC1–AC4）

订单 1899 /【S5-DOC-003】。本文件把四条验收标准逐条对应到**代码行、测试节点、断言语句、证据文件**，
方便直接核对，不需要通读整个仓库。

仓库：<https://github.com/liaoyuqing/clawhunt-1899-contract-upload>（public，main 分支）

两套测试，全部实跑：

- 默认套件（moto + SQLite）：**44 passed**，14 skipped（真实环境套件在无外部服务时整体跳过），退出码 0；
- 真实环境套件（真 MinIO 服务端 + PostgreSQL 16.4）：**14 passed**，退出码 0，原始输出在 `evidence/` 下。

逐文件分跑结果见 §6，真实环境复核的完整说明见 §5。

---

## 0. 一页速查

| AC | 原文 | 实现位置 | 测试节点 | 关键断言 | 证据文件 |
|---|---|---|---|---|---|
| **AC1** | 上传 4 种允许格式均返回 201，并能在 MinIO 中看到对应对象（测试输出） | `app/doc/service.py:74-224`、`app/doc/types.py:90-124`、`app/storage/s3_adapter.py:169-176` | `tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[pdf\|docx\|jpg\|png]` | `assert response.status_code == 201`、`assert len(new_keys) == 1`、`assert adapter.object_exists(key)` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log`、**`evidence/ac1-minio-upload.txt`、`evidence/ac1-minio-head.txt`、`evidence/ac1-minio-mc-ls.txt`、`evidence/ac1-bucket-private.txt`（真 MinIO）** |
| **AC2** | 上传 21 MB 文件返回 413，上传 .exe 返回 415（pytest 通过） | `app/doc/service.py:107-146`、`app/doc/streaming.py:117-161`、`app/doc/types.py:66-78` | `tests/test_ac2_limits.py::test_ac2_21mb_is_rejected_with_413`、`::test_ac2_exe_is_rejected_with_415` | `assert response.status_code == 413`、`assert response.status_code == 415`、`assert adapter.list_keys() == []` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log` |
| **AC3** | 同一文件重复上传返回 409，body 中 contract_id 与首次一致 | `app/doc/service.py:160-209`、`migrations/versions/0001_init.py:44-51` | `tests/test_ac3_duplicates.py::test_ac3_duplicate_upload_returns_409_with_the_same_contract_id` | `assert second.status_code == 409`、`assert body["contract_id"] == first_id`、`assert count == 1` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log`、**`evidence/ac3-pg-alembic.txt`、`evidence/ac3-pg-index.txt`、`evidence/ac3-pg-tests.txt`（真 PG 16）** |
| **AC4** | 预签名地址超过 5 分钟后失效（冻结时间的单元测试证明） | `app/storage/s3_adapter.py:294-315`、`app/storage/signing.py:113-191`、`app/doc/service.py:227-268` | `tests/test_ac4_presign.py::test_ac4_expires_parameter_equals_injected_moment_plus_300`、`::test_ac4_url_is_valid_at_299_seconds_and_expired_at_301_seconds` | `assert query["X-Amz-Expires"] == ["300"]`、`assert body["expires_at"] == expected.isoformat()`、`assert is_expired(url, now=expired) is True` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log`、**`evidence/ac4-presign-expiry.txt`（真 MinIO，4:59→200 / 5:01→403）** |

---

## 1. AC1 · 上传 4 种允许格式均返回 201，并能在 MinIO 中看到对应对象

### 1.1 验收原文

> 上传 4 种允许格式均返回 201，并能在 MinIO 中看到对应对象（测试输出）

### 1.2 实现位置（哪一行代码）

| 环节 | 位置 | 说明 |
|---|---|---|
| 接口入口 | `app/doc/api/contracts.py:37-88` | `POST /api/doc/contracts`，`multipart/form-data`，`file` + 两个可选字段 |
| 格式双判 | `app/doc/types.py:16-31`（白名单 + magic number 常量）、`app/doc/types.py:66-78`（`detect_content_type`）、`app/doc/types.py:90-124`（`resolve_extension`：真实类型与扩展名不一致即拒绝） | PDF `%PDF-` / DOCX `PK` + `[Content_Types].xml` / JPG `FF D8 FF` / PNG `89 50 4E 47` |
| 流式写入 | `app/doc/streaming.py:117-161`（`stream_to_object`）、`app/doc/streaming.py:47-104`（`MultipartWriter`） | 1 MB 分块，边读边算 sha256 与累计 size |
| 对象落桶 | `app/doc/service.py:212`（`outcome.writer.finish()`）→ `app/storage/s3_adapter.py:169-176`（`put_object`）、`app/storage/s3_adapter.py:178-238`（`put_stream`） | 对象真正可见是在查重之后 |
| key 生成 | `app/doc/keys.py:29-55`（`build_object_key`） | `contracts/{org_id}/{yyyy}/{mm}/{uuid4}.{ext}`，yyyy/mm 取站点时区 |
| 私有桶 | `app/storage/s3_adapter.py:76-146`（`ensure_bucket` / `_enforce_private`） | `private` ACL + public access block + 拒绝 public ACL 的 bucket policy |

### 1.3 测试节点与可复制命令

```bash
python -m pytest tests/test_ac1_formats.py -q

# 单个格式（把 pdf 换成 docx / jpg / png 即可）
python -m pytest "tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[pdf]" -v
```

节点 id：

- `tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[pdf]`
- `tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[docx]`
- `tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[jpg]`
- `tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[png]`
- `tests/test_ac1_formats.py::test_ac1_bucket_is_not_public_read`

### 1.4 断言的具体值

`tests/test_ac1_formats.py:28-41`：

```python
assert response.status_code == 201, response.text      # 四种格式都是 201
assert set(body) == {"contract_id", "status"}          # 响应体恰 2 键
assert body["status"] == "uploaded"
assert len(new_keys) == 1, new_keys                      # 桶内新增对象恰 1 个
assert KEY_PATTERN.match(key), key                      # key 形如 contracts/org/yyyy/mm/uuid4.ext
assert is_valid_object_key(key, org_id=ORG_ID), key
assert key.endswith("." + ext), key                    # 扩展名与格式一致
assert adapter.object_exists(key)                       # 对象在 MinIO 里确实存在
assert adapter.head_object(key)["ContentLength"] == len(payload)   # 字节数与源文件一致
```

`tests/test_ac1_formats.py:46-50`：

```python
assert adapter.is_public_read() is False                # 桶不是 public-read
assert statements, policy                               # bucket policy 里没有匿名 Allow
```

### 1.5 证据文件

- `docs/checks/pytest.log` —— 全量 `pytest -v` 输出，含 `test_ac1_each_allowed_format_returns_201[pdf]` 等四个节点名与 `PASSED` 标记；末尾汇总 `44 passed`。
- `docs/checks/clone-verify.log` —— 干净 clone（`C:\Users\Public\_v1899`）上的同一批输出，含 `--- command: python -m pytest -q ---` 与 `exit code: 0`。
- `docs/openapi.json` —— `scripts/check_openapi.py` 导出的接口描述，上传接口声明 `multipart/form-data` 与 413/415/409/403。
- **`evidence/ac1-minio-upload.txt`** —— 真 MinIO 服务端上重跑同一批断言（6 passed），断言含 `object_exists` 与 `head_object` 字节数。
- **`evidence/ac1-minio-head.txt`** —— 桶内四个对象的 `ContentLength` / `ContentType` / `ETag` / `LastModified`。
- **`evidence/ac1-minio-mc-ls.txt`** —— `mc ls --recursive` 直接列出这四个对象，桶内恰好 4 个。
- **`evidence/ac1-bucket-private.txt`** —— 真 MinIO 上 `is_public_read()=False`、ACL 无 AllUsers 授权、匿名 GET 403。

---

## 2. AC2 · 上传 21 MB 文件返回 413，上传 .exe 返回 415

### 2.1 验收原文

> 上传 21 MB 文件返回 413，上传 .exe 返回 415（pytest 通过）

### 2.2 实现位置（哪一行代码）

| 环节 | 位置 | 说明 |
|---|---|---|
| 扩展名先筛 | `app/doc/service.py:100-113` | 扩展名不在白名单直接 415，连文件都不读 |
| 流式累计 | `app/doc/streaming.py:23`（`CHUNK_SIZE = 1024 * 1024`）、`app/doc/streaming.py:138-148` | 每块 1 MB；`size += len(chunk)` 后 `if size > max_size:` 立即中止 |
| 超限中止 | `app/doc/streaming.py:147`（`writer.abort()`）、`app/doc/streaming.py:107-115`（`abort` → `abort_multipart`） | 已写分片全部删除，桶内不留半个对象 |
| 413 响应 | `app/doc/service.py:134-145` | `except UploadTooLargeError` → `status_code=413` |
| 415 响应 | `app/doc/service.py:150-156`（`resolve_extension` 抛错 → `outcome.writer.abort()`） | 真实类型与扩展名不一致 ⇒ 415 |
| 不信 Content-Length | `app/doc/service.py:69-72`（`_chunks` 按块 read，从不读该头） | 客户端可以撒谎 |

### 2.3 测试节点与可复制命令

```bash
python -m pytest tests/test_ac2_limits.py -q

python -m pytest tests/test_ac2_limits.py::test_ac2_21mb_is_rejected_with_413 -v
python -m pytest tests/test_ac2_limits.py::test_ac2_exe_is_rejected_with_415 -v
```

节点 id（`tests/test_ac2_limits.py`）：

| 行号 | 节点 id | 覆盖的场景 | 期望 |
|---|---|---|---|
| 29 | `test_ac2_21mb_is_rejected_with_413` | 21 MB | 413 |
| 40 | `test_ac2_exe_is_rejected_with_415` | `.exe` | 415 |
| 48 | `test_ac2_exe_renamed_to_pdf_is_rejected_with_415` | `.exe` 改名 `.pdf` | 415 |
| 56 | `test_ac2_pdf_content_with_png_extension_is_rejected` | PDF 内容配 `.png` 后缀 | 415 |
| 64 | `test_boundary_exactly_20mb_is_accepted` | 恰好 20 MB | 201 |
| 75 | `test_boundary_20mb_plus_one_byte_is_rejected` | 20 MB + 1 字节 | 413 |
| 85 | `test_413_leaves_no_object_and_no_pending_multipart` | 413 后桶内残留 | 0 对象 0 pending multipart |
| 95 | `test_content_length_lie_is_ignored` | `Content-Length` 撒谎 | 413 |

### 2.4 断言的具体值

```python
# test_ac2_21mb_is_rejected_with_413
assert len(payload) == 21 * MB
assert response.status_code == 413, response.text
assert after == before, "a rejected upload must not leave an object behind"

# test_ac2_exe_is_rejected_with_415
assert response.status_code == 415, response.text

# test_413_leaves_no_object_and_no_pending_multipart
assert adapter.list_keys() == []
pending = adapter.client.list_multipart_uploads(Bucket=adapter.bucket).get("Uploads")
assert not pending, pending

# test_boundary_exactly_20mb_is_accepted
assert response.status_code == 201, response.text
assert len(keys) == 1
assert adapter.head_object(keys[0])["ContentLength"] == 20 * MB

# test_content_length_lie_is_ignored
assert response.status_code == 413, response.text
assert adapter.list_keys() == []
```

### 2.5 证据文件

- `docs/checks/pytest.log` —— 含上表 8 个节点名与 `PASSED` 标记。
- `docs/checks/clone-verify.log` —— 干净 clone 上的同一批输出。

---

## 3. AC3 · 同一文件重复上传返回 409，body 中 contract_id 与首次一致

### 3.1 验收原文

> 同一文件重复上传返回 409，body 中 contract_id 与首次一致

### 3.2 实现位置（哪一行代码）

| 环节 | 位置 | 说明 |
|---|---|---|
| 查重语句 | `app/doc/service.py:63-70`（`_find_existing`）、`app/doc/service.py:162`（调用点） | `(org_id, sha256, deleted_at IS NULL)` |
| 命中即 409 | `app/doc/service.py:203-209` | `duplicate=True` → `status_code=409`，body 带 `contract_id`（既有 id） |
| 不留孤儿对象 | `app/doc/service.py:204`（`outcome.writer.abort()`） | 命中时对象尚未完成提交，桶里不会多出对象 |
| 唯一索引 | `migrations/versions/0001_init.py:44-51` | `CREATE UNIQUE INDEX uq_doc_contract_org_sha256_active ON doc_contract (org_id, sha256) WHERE deleted_at IS NULL` |
| 软删后可重传 | `app/doc/service.py:63-70`（`deleted_at.is_(None)` 过滤）+ 上述部分唯一索引 | 软删行不再参与唯一约束 |

迁移实际生成的 DDL（干净 clone 上 `alembic upgrade head` 后从 `sqlite_master` 读出，见 `docs/checks/clone-verify.log`）：

```sql
CREATE UNIQUE INDEX uq_doc_contract_org_sha256_active ON doc_contract (org_id, sha256) WHERE deleted_at IS NULL
```

### 3.3 测试节点与可复制命令

```bash
python -m pytest tests/test_ac3_duplicates.py -q

python -m pytest tests/test_ac3_duplicates.py::test_ac3_duplicate_upload_returns_409_with_the_same_contract_id -v
```

节点 id：

- `tests/test_ac3_duplicates.py::test_ac3_duplicate_upload_returns_409_with_the_same_contract_id`（第 20 行）
- `tests/test_ac3_duplicates.py::test_ac3_duplicate_in_another_org_is_allowed`（第 48 行）
- `tests/test_ac3_duplicates.py::test_ac3_reupload_after_soft_delete_creates_a_new_contract`（第 58 行）

### 3.4 断言的具体值

```python
assert first.status_code == 201, first.text
first_id = first.json()["contract_id"]
assert len(keys_after_first) == 1

assert second.status_code == 409, response.text
assert body["contract_id"] == first_id          # ← AC3 的核心：与首次一致
assert set(body) == {"contract_id", "status"}

count = session.execute(select(func.count()).select_from(DocContract).where(
    DocContract.org_id == ORG_ID, DocContract.deleted_at.is_(None),
)).scalar_one()
assert count == 1, count                        # ← 库里只有 1 条记录
assert adapter.list_keys() == keys_after_first  # ← 桶里对象数不增加

# 软删后重传
assert second.status_code == 201, response.text
assert second_id != first_id                    # ← 新 id
assert active == 1
```

### 3.5 证据文件

- `docs/checks/pytest.log` —— 含三个节点名与 `PASSED` 标记。
- `docs/checks/clone-verify.log` —— 干净 clone 上的同一批输出。
- **`evidence/ac3-pg-alembic.txt`** —— 真 PostgreSQL 16.4 上 `alembic current` / `upgrade head` / `current`，退出码全 0。
- **`evidence/ac3-pg-index.txt`** —— `pg_indexes` 里那条部分唯一索引的实际定义（`CREATE UNIQUE INDEX ... WHERE (deleted_at IS NULL)`）。
- **`evidence/ac3-pg-tests.txt`** —— 真 PG 上重复上传 409 同 id、软删后重传、**十并发 1×201 + 9×409**（5 passed）。

---

## 4. AC4 · 预签名地址超过 5 分钟后失效（冻结时间的单元测试证明）

### 4.1 验收原文

> 预签名地址超过 5 分钟后失效（冻结时间的单元测试证明）

### 4.2 实现位置（哪一行代码）

| 环节 | 位置 | 说明 |
|---|---|---|
| 过期秒数参数注入 | `app/storage/s3_adapter.py:294-315`（`presigned_get_url(key, expires_in=300, now=None)`） | 默认 300 秒；`now` 可注入时钟 |
| 过期时刻换算 | `app/storage/s3_adapter.py:318-336`（`_expiry_from_presigned_url`） | 与签名使用**同一时钟**计算 `expires_at` |
| 预签名参数 | `app/storage/s3_adapter.py:310-313` | URL 里的 `X-Amz-Date` 与 `X-Amz-Expires` |
| 服务端同规则的过期判定 | `app/storage/signing.py:47-74`（解析）、`app/storage/signing.py:113-154`（复算 SigV4 签名）、`app/storage/signing.py:157-182`（`verify_presigned_url`）、`app/storage/signing.py:185-191`（`is_expired`） | 判定式：`now >= X-Amz-Date + X-Amz-Expires` 即失效 |
| 接口返回两键 | `app/doc/service.py:227-268`（`presign_download`）、`app/doc/api/contracts.py:91-113` | `{url, expires_at}` |

### 4.3 测试节点与可复制命令

```bash
python -m pytest tests/test_ac4_presign.py -q

python -m pytest tests/test_ac4_presign.py::test_ac4_expires_parameter_equals_injected_moment_plus_300 -v
python -m pytest tests/test_ac4_presign.py::test_ac4_url_is_valid_at_299_seconds_and_expired_at_301_seconds -v
```

节点 id：

- `tests/test_ac4_presign.py::test_ac4_download_response_has_exactly_two_keys`（第 31 行）
- `tests/test_ac4_presign.py::test_ac4_expires_parameter_equals_injected_moment_plus_300`（第 41 行）
- `tests/test_ac4_presign.py::test_ac4_url_is_valid_at_299_seconds_and_expired_at_301_seconds`（第 56 行）
- `tests/test_ac4_presign.py::test_ac4_signature_matches_the_server_side_algorithm`（第 76 行）
- `tests/test_ac4_presign.py::test_ac4_expires_in_is_a_parameter_default_300`（第 87 行）

### 4.4 断言的具体值

```python
# 冻结时刻 2026-03-01T12:00:00Z 发起下载（freezegun）
frozen = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
expected = frozen + timedelta(seconds=300)

assert query["X-Amz-Expires"] == ["300"]          # ← 过期秒数 = 5 分钟
assert body["expires_at"] == expected.isoformat() # ← expires_at = 注入时刻 + 300
assert parse_presigned_url(body["url"]).expires_at == expected

# 4 分 59 秒 / 5 分 01 秒 成对断言
assert info.expires_in == 300
assert is_expired(url, now=info.amz_date + timedelta(seconds=299)) is False   # ← 仍有效
ok, reason = verify_presigned_url(url, SECRET, now=info.amz_date + timedelta(seconds=299))
assert ok, reason
assert is_expired(url, now=info.amz_date + timedelta(seconds=301)) is True    # ← 已失效
assert not ok
assert "expired" in reason

# 签名确实是服务端同款的 SigV4
assert compute_signature(info, SECRET) == info.signature
assert verify_presigned_url(url, SECRET)[0] is True
assert verify_presigned_url(url, "the-wrong-secret")[0] is False

# 过期秒数确实是参数（默认 300，可注入别的值）
assert parse_qs(urlparse(default.url).query)["X-Amz-Expires"] == ["300"]
assert parse_qs(urlparse(injected.url).query)["X-Amz-Expires"] == ["60"]
```

### 4.5 证据文件

- `docs/checks/pytest.log` —— 含五个节点名与 `PASSED` 标记。
- `docs/checks/clone-verify.log` —— 干净 clone 上的同一批输出。
- **`evidence/ac4-presign-expiry.txt`** —— 真 MinIO 上同一批 URL：age 299s ⇒ **HTTP 200（65 字节）**、age 301s ⇒ **HTTP 403 `AccessDenied`**，
  判决由 MinIO 自己的时钟作出（3 passed）。这一份替代了上一版「只能证明我们自己认为过期」的弱点。

---

## 5. 真实环境复核：真 MinIO 服务端 + PostgreSQL 16（本版新增）

上一版的四段证据全部跑在 moto + SQLite 上，买方因此驳回。本版补了这一节：**同样的代码，跑在真的 MinIO 服务端和真的
PostgreSQL 16 上**，原始输出逐份落盘在 `evidence/` 下，不再有任何「本机没有 MinIO / 没有 PostgreSQL」的说法。

### 5.1 交付机器上实际在跑的服务

| 服务 | 版本 | 端点 | 启动方式 |
|---|---|---|---|
| MinIO 服务端 | `RELEASE.2025-07-23T15-54-02Z` | `http://127.0.0.1:9000` | 官方 `minio.exe` 直跑（无 docker），数据目录 `D:\minio1899data` |
| MinIO 客户端 | `mc RELEASE.2026-09-19T15-24-59Z` | — | alias `local1899` |
| PostgreSQL | `16.4` | `127.0.0.1:55432` | 本机实例，库 `contracts_realenv`，用户 `postgres` |

### 5.2 新增的测试套件 `tests/realenv/`（14 例）

| 文件 | 用例 | 覆盖 | 需要的外部服务 |
|---|---|---|---|
| `tests/realenv/test_ac1_minio.py` | 6 | AC1 四格式 201 + `head_object` 字节数 + 桶私有 + 匿名 GET 403 + manifest | 真 MinIO + PG |
| `tests/realenv/test_ac4_minio.py` | 3 | AC4 由 MinIO 判定的 4:59 / 5:01 边界 | 真 MinIO + PG |
| `tests/realenv/test_ac3_postgres.py` | 5 | PG 版本、部分唯一索引定义、409 同 id、软删重传、十并发 | 真 MinIO + PG |

三个环境变量（`CONTRACT_TEST_S3_ENDPOINT` / `CONTRACT_TEST_S3_SECRET_KEY` / `CONTRACT_TEST_DATABASE_URL`）缺任意一个时，
`requires_real_env` 让这 14 例整体 skip，默认套件仍是 44 passed（见 §6.1）。

### 5.3 AC1：在真 MinIO 里确实看到了那四个对象

证据 `evidence/ac1-minio-upload.txt`（`python -m pytest -v -s tests/realenv/test_ac1_minio.py`，**6 passed**，退出码 0）：

```
tests/realenv/test_ac1_minio.py::test_ac1_each_allowed_format_returns_201_on_real_minio[pdf] PASSED
tests/realenv/test_ac1_minio.py::test_ac1_each_allowed_format_returns_201_on_real_minio[docx] PASSED
tests/realenv/test_ac1_minio.py::test_ac1_each_allowed_format_returns_201_on_real_minio[jpg] PASSED
tests/realenv/test_ac1_minio.py::test_ac1_each_allowed_format_returns_201_on_real_minio[png] PASSED
tests/realenv/test_ac1_minio.py::test_ac1_bucket_is_not_public_read_on_real_minio PASSED
tests/realenv/test_ac1_minio.py::test_ac1_manifest_covers_all_four_formats PASSED
======================== 6 passed, 1 warning in 2.25s =========================
```

每个格式的断言（`tests/realenv/test_ac1_minio.py`）：

```python
assert response.status_code == 201, response.text          # 四种格式都是 201
new_keys = set(adapter.list_keys()) - before                 # 桶内新增对象恰 1 个
assert len(new_keys) == 1, new_keys
assert key.endswith("." + ext), key                          # 扩展名与格式一致
assert adapter.object_exists(key)                            # 对象在真 MinIO 里存在
head = adapter.head_object(key)
assert head["ContentLength"] == len(payload), (head["ContentLength"], len(payload))
```

四条 `mc ls --recursive` 直接列出的对象（`evidence/ac1-minio-mc-ls.txt`，桶内**恰好 4 个**）：

```
[2026-11-25 13:11:13 CST]    65B STANDARD contracts/org-realenv-0001-090562bcf8/2026/11/d806203b-2dee-4d66-9906-45056c6d16f0.pdf
[2026-11-25 13:11:13 CST]    36B STANDARD contracts/org-realenv-0001-2b2bb446a5/2026/11/39467f86-553d-46d3-9a74-a27c2c3bd2dd.jpg
[2026-11-25 13:11:14 CST]    44B STANDARD contracts/org-realenv-0001-5e8bd1be29/2026/11/c5a95d44-c93f-4723-bcaa-0f53eee4660c.png
[2026-11-25 13:11:13 CST]   584B STANDARD contracts/org-realenv-0001-fc475d4278/2026/11/f9078b69-230a-4952-a000-f8d1d56ef96d.docx
```

`head_object` 回来的 `ContentLength` 与源文件字节数逐个相等（`evidence/ac1-minio-head.txt`）：

```
{"object_key": "contracts/org-realenv-0001-090562bcf8/2026/11/d806203b-...pdf",  "ContentLength": 65,  "ContentType": "application/pdf"}
{"object_key": "contracts/org-realenv-0001-2b2bb446a5/2026/11/39467f86-...jpg",  "ContentLength": 36,  "ContentType": "image/jpeg"}
{"object_key": "contracts/org-realenv-0001-5e8bd1be29/2026/11/c5a95d44-...png",  "ContentLength": 44,  "ContentType": "image/png"}
{"object_key": "contracts/org-realenv-0001-fc475d4278/2026/11/f9078b69-...docx", "ContentLength": 584, "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
```

桶私有性在真 MinIO 上的复核（`evidence/ac1-bucket-private.txt`）：

```
is_public_read() = False
bucket ACL grants = [ {"grantee": null, "permission": "FULL_CONTROL"} ]     ← 没有 AllUsers 授权
bucket policy = { Statement: [ { Sid: DenyPublicObjectAcl, Effect: Deny,
                                 Action: [s3:PutObjectAcl], Principal: {AWS:[*]}} ] }
anonymous GET http://127.0.0.1:9000/contract-realenv-ac1/...  -> HTTP 403, <Code>AccessDenied</Code>
```

### 5.4 AC4：4:59 → 200 / 5:01 → 403，判决由 MinIO 作出

这是本版最关键的一处补强。上一版只能证明「我们自己的校验器认为过期了」，买方要的是**服务端**的判决。

证据 `evidence/ac4-presign-expiry.txt`（**3 passed**，退出码 0）：

```
tests/realenv/test_ac4_minio.py::test_ac4_url_still_valid_at_4m59s_on_real_minio
  age 299s = 4:59 -> HTTP 200, 65 bytes, expires_at=2026-11-25T05:11:19+00:00 PASSED
tests/realenv/test_ac4_minio.py::test_ac4_url_expired_at_5m01s_on_real_minio
  age 301s = 5:01 -> HTTP 403, code=AccessDenied, expires_at=2026-11-25T05:11:18+00:00 PASSED
tests/realenv/test_ac4_minio.py::test_ac4_expiry_is_a_server_side_verdict_not_our_check PASSED
```

做法与为什么这样仍算「5 分钟」：

1. 应用按正常流程签发下载 URL（`presign_ttl_seconds=300`），URL 里带 `X-Amz-Date` 与 `X-Amz-Expires=300`。
2. 签发瞬间用 freezegun 把**签发侧**时钟冻结在 `now - age`，于是 URL 的 `X-Amz-Date` 正好是 `age` 秒之前；
   三个断言把这个事实钉死：`parse_presigned_url(url).expires_in == 300`、`parse_presigned_url(url).amz_date == signed_at`、
   `int((now - amz_date).total_seconds()) == 299 / 301`。

   取样点故意落在整秒之后 **0.4 秒**，而不是压在边界上：这样「4:59」这一侧的 URL 在 MinIO 眼里是 299.4 秒，
   距 300 秒的判决边界还有 0.6 秒余量 —— 否则采样时刻的一点抖动就会让 403 变成「正确的判决、错误的说法」。
   `_presign_aged()` 里那 0.4 秒 sleep 就是为此，连跑 5 次结果稳定。
3. 然后**用真实时钟**去 GET 这个 URL。判定的只有 MinIO：它比对 `X-Amz-Date + X-Amz-Expires` 与**它自己的墙钟**。
   本仓库在这条路径上没有参与判定 —— 403 是 MinIO 回的，`<Code>AccessDenied</Code>` 是 MinIO 写在 body 里的。

等价地：这一步替换的只是「URL 有多老」这个取样点，**判决逻辑与时钟都属于 MinIO**。

### 5.5 AC3：真 PostgreSQL 16 上的 `alembic upgrade head` 与十并发

`evidence/ac3-pg-alembic.txt`：

```
$ python -m alembic current        -> 0001_init (head)      exit code: 0
$ python -m alembic upgrade head   -> (无变更, 已在 head)    exit code: 0
$ python -m alembic current        -> 0001_init (head)      exit code: 0
Context impl PostgresqlImpl. / Will assume transactional DDL.
```

迁移在该库实际建出的索引（`evidence/ac3-pg-index.txt`，读自 `pg_indexes`）：

```sql
CREATE UNIQUE INDEX uq_doc_contract_org_sha256_active
  ON public.doc_contract USING btree (org_id, sha256) WHERE (deleted_at IS NULL)
```

`evidence/ac3-pg-tests.txt`（**5 passed**，退出码 0）：

```
test_postgres_16_is_the_backend            backend: PostgreSQL 16.4
test_partial_unique_index_exists_with_the_where_clause
  index: CREATE UNIQUE INDEX uq_doc_contract_org_sha256_active ON public.doc_contract
         USING btree (org_id, sha256) WHERE (deleted_at IS NULL)
test_ac3_duplicate_upload_returns_409_with_the_same_contract_id_on_postgres  PASSED
test_ac3_reupload_after_soft_delete_on_postgres                              PASSED
test_ten_concurrent_uploads_of_the_same_file_yield_one_201_on_postgres
  concurrent codes: [201, 409, 409, 409, 409, 409, 409, 409, 409, 409] -> one 201, nine 409 PASSED
```

十并发那条的断言（`tests/realenv/test_ac3_postgres.py`）：

```python
codes = [code for code, _ in results]
assert codes.count(201) == 1, codes
assert codes.count(409) == 9, codes
winners = {body["contract_id"] for code, body in results if code == 201}
losers  = {body["contract_id"] for code, body in results if code == 409}
assert len(winners) == 1, winners
assert losers == winners, (losers, winners)      # 九个 409 带的都是同一个 id
assert len(active) == 1                          # 库里只有一行
```

这一条是 SQLite 无法替代的：部分唯一索引在**并发插入**下的行为、以及落败方拿到的是 `IntegrityError` 而不是
`OperationalError`，两个数据库不一样。真 PG 上跑通才算证据。

### 5.6 为什么真实 MinIO 逼出了一处适配器修正

真 MinIO 在「把桶设私有」上与 AWS S3 有三处不同，原来的 `_enforce_private` 在真机上会直接抛错：

| 动作 | AWS S3 / moto | 真 MinIO | 修正后做法 |
|---|---|---|---|
| `put_bucket_acl(ACL=private)` | 生效 | 200 但空操作 | 照发；`NotImplemented`/`501` 视为可接受 |
| `put_public_access_block` | 生效 | `MalformedXML` | 容忍 `MalformedXML`，best effort |
| policy 里的 `s3:x-amz-acl` 条件键 | 支持 | `MalformedPolicy - invalid condition key` | 先带条件，失败退到不带条件的 MinIO 形式 |
| `s3:PutObjectAcl` 只列对象 resource | 接受 | `unsupported Resource found` | MinIO 形式同时列对象与桶两个 resource |

`app/storage/s3_adapter.py: _enforce_private` 与新增的 `_private_policy(*, conditioned: bool)` 就是这么改的。
两种 policy 形式**都是 Deny-only**，不会授予任何匿名权限；改完默认套件仍 44 passed（见 §6.1）。

### 5.7 怎样一键复现这一节

```bash
# 1) 起真 MinIO（无 docker 时用二进制）
minio server /data --address 127.0.0.1:9000
mc alias set local1899 http://127.0.0.1:9000 minioadmin minioadmin

# 2) 指向真 PostgreSQL 16 的空库
createdb -h 127.0.0.1 -p 55432 -U postgres contracts_realenv

# 3) 三个变量 + 一个桶名，跑真实环境套件并生成证据
export CONTRACT_TEST_S3_ENDPOINT=http://127.0.0.1:9000
export CONTRACT_TEST_S3_SECRET_KEY=minioadmin
export CONTRACT_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/contracts_realenv
python -m pytest tests/realenv -q        # 14 passed
python scripts/realenv_evidence.py       # 重新生成 evidence/*.txt
```

`scripts/realenv_evidence.py` 只做三件事：跑三组 pytest 并把 stdout 原样落盘、用 `mc ls` / `head_object` / `get_bucket_acl`
把服务端看到的东西打印出来、跑 `alembic current` / `upgrade head` 并把输出落盘。没有任何一个数值是脚本自己编的。

---

## 6. 逐文件用例数与耗时

### 6.1 默认套件（moto + SQLite）

干净 clone（`C:\Users\Public\_v1899`）上逐文件实测，全部退出码 0：

| 测试文件 | 用例数 | 覆盖 |
|---|---|---|
| `tests/test_ac1_formats.py` | 5 | AC1：四格式 201 + 桶私有 |
| `tests/test_ac2_limits.py` | 8 | AC2：413 / 415 / 边界 / 清理 / 撒谎头 |
| `tests/test_ac3_duplicates.py` | 3 | AC3：409 同 id / 跨组织 / 软删重传 |
| `tests/test_ac4_presign.py` | 5 | AC4：Expires 参数 / 299-301 边界 / 签名 |
| `tests/test_concurrency.py` | 1 | 10 并发同文件 ⇒ 1×201 + 9×409 |
| `tests/test_permissions.py` | 3 | 跨 org 404 逐字节相同 / 403 |
| `tests/test_config.py` | 8 | 三项配置缺失 / 空串启动期抛错 |
| `tests/test_keys.py` | 5 | key 形状 / 跨年跨月 / 1000 次无重复 |
| `tests/test_dispatch.py` | 3 | 投递桩失败仍 201 + outbox 1 行 + 重试任务恰 1 行 |
| `tests/test_filename_handling.py` | 3 | `../../x.pdf` / 非 ASCII 文件名 / 无扩展名 415 |
| **合计** | **44** | `python -m pytest -q` → `44 passed`，退出码 0 |

### 6.2 真实环境套件（真 MinIO + PostgreSQL 16.4）

| 测试文件 | 用例数 | 覆盖 | 证据 |
|---|---|---|---|
| `tests/realenv/test_ac1_minio.py` | 6 | 四格式 201 + `head_object` 字节数 + 桶私有 + 匿名 GET 403 | `evidence/ac1-minio-upload.txt`、`evidence/ac1-bucket-private.txt`、`evidence/ac1-minio-head.txt`、`evidence/ac1-minio-mc-ls.txt` |
| `tests/realenv/test_ac4_minio.py` | 3 | MinIO 判定的 4:59 → 200 / 5:01 → 403 | `evidence/ac4-presign-expiry.txt` |
| `tests/realenv/test_ac3_postgres.py` | 5 | PG 16.4、部分唯一索引、409 同 id、软删重传、十并发 | `evidence/ac3-pg-tests.txt`、`evidence/ac3-pg-index.txt`、`evidence/ac3-pg-alembic.txt` |
| **合计** | **14** | `python -m pytest tests/realenv -q` → `14 passed`，退出码 0 | 见上 |

无 `CONTRACT_TEST_*` 变量时这 14 例整体 skip，默认套件仍是 44 passed：

```
python -m pytest -q                    -> 44 passed, 14 skipped   exit code 0
python -m pytest tests/realenv -q      -> 14 passed                exit code 0（需真 MinIO + PG）
```

---

## 7. 一条命令跑完四条 AC

```bash
python scripts/verify_ac.py
```

该脚本依次执行四个 AC 对应的 pytest 节点，逐条打印 `AC1 PASS` … `AC4 PASS` 与耗时，
全部通过时退出码 0，任一条失败时退出码 1。

本机实测输出（完整日志见 `docs/checks/verify-ac.log`）：

```
=== AC1: 上传 4 种允许格式均返回 201，并能在 MinIO 中看到对应对象 ===
AC1 PASS  (5 node(s), 7.21s)
=== AC2: 上传 21 MB 文件返回 413，上传 .exe 返回 415 ===
AC2 PASS  (8 node(s), 12.71s)
=== AC3: 同一文件重复上传返回 409，body 中 contract_id 与首次一致 ===
AC3 PASS  (3 node(s), 5.59s)
=== AC4: 预签名地址超过 5 分钟后失效（冻结时间的单元测试证明） ===
AC4 PASS  (5 node(s), 6.80s)
all four acceptance criteria PASS
```