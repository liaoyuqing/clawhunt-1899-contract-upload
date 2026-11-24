# 验收证据对照表（AC1–AC4）

订单 1899 /【S5-DOC-003】。本文件把四条验收标准逐条对应到**代码行、测试节点、断言语句、证据文件**，
方便直接核对，不需要通读整个仓库。

仓库：<https://github.com/liaoyuqing/clawhunt-1899-contract-upload>（public，main 分支）

全量用例实测：**44 passed**（干净 clone 上 `python -m pytest -q` 退出码 0），
逐文件分跑结果见 [§4](#4-逐文件用例数与耗时)。

---

## 0. 一页速查

| AC | 原文 | 实现位置 | 测试节点 | 关键断言 | 证据文件 |
|---|---|---|---|---|---|
| **AC1** | 上传 4 种允许格式均返回 201，并能在 MinIO 中看到对应对象（测试输出） | `app/doc/service.py:74-224`、`app/doc/types.py:90-124`、`app/storage/s3_adapter.py:169-176` | `tests/test_ac1_formats.py::test_ac1_each_allowed_format_returns_201[pdf\|docx\|jpg\|png]` | `assert response.status_code == 201`、`assert len(new_keys) == 1`、`assert adapter.object_exists(key)` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log` |
| **AC2** | 上传 21 MB 文件返回 413，上传 .exe 返回 415（pytest 通过） | `app/doc/service.py:107-146`、`app/doc/streaming.py:117-161`、`app/doc/types.py:66-78` | `tests/test_ac2_limits.py::test_ac2_21mb_is_rejected_with_413`、`::test_ac2_exe_is_rejected_with_415` | `assert response.status_code == 413`、`assert response.status_code == 415`、`assert adapter.list_keys() == []` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log` |
| **AC3** | 同一文件重复上传返回 409，body 中 contract_id 与首次一致 | `app/doc/service.py:160-209`、`migrations/versions/0001_init.py:44-51` | `tests/test_ac3_duplicates.py::test_ac3_duplicate_upload_returns_409_with_the_same_contract_id` | `assert second.status_code == 409`、`assert body["contract_id"] == first_id`、`assert count == 1` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log` |
| **AC4** | 预签名地址超过 5 分钟后失效（冻结时间的单元测试证明） | `app/storage/s3_adapter.py:294-315`、`app/storage/signing.py:113-191`、`app/doc/service.py:227-268` | `tests/test_ac4_presign.py::test_ac4_expires_parameter_equals_injected_moment_plus_300`、`::test_ac4_url_is_valid_at_299_seconds_and_expired_at_301_seconds` | `assert query["X-Amz-Expires"] == ["300"]`、`assert body["expires_at"] == expected.isoformat()`、`assert is_expired(url, now=expired) is True` | `docs/checks/pytest.log`、`docs/checks/clone-verify.log` |

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

---

## 5. 本机运行环境边界（为什么 AC4 用冻结时间也能成立）

这一节说明本单**实际**的验证环境，以及它为什么仍然能证明 AC4。

### 5.1 事实

| 项 | 实际情况 |
|---|---|
| docker | **没有**。本机无法启动任何容器。 |
| 真 MinIO 服务端 | **没有**。因此 `deploy/docker-compose.minio.yml` **作为交付物提供，本机从未运行过**（文件头已注明）。 |
| 测试用的对象存储 | **moto 的 `ThreadedMotoServer`**（`tests/conftest.py:38-45`）：一个真正的 HTTP 服务器，boto3 通过**真实 HTTP 协议栈**访问它——SigV4 签名、multipart 上传、预签名 URL 全部走网络请求，不是进程内拦截。 |
| moto 的过期校验 | moto **不校验预签名过期**。实测：`ExpiresIn=1` 生成的 URL，放 2.5 秒后 GET 仍返回 200；把签名时间冻结到 2024 年也仍返回 200。 |
| freezegun 的作用 | 冻结**应用侧**时钟（`app/doc/service.py` 的 `now`、`app/storage/s3_adapter.py` 的 `now`），使 `expires_at` 与过期边界可复现。**不**用于模拟 MinIO 的服务端时钟。 |

### 5.2 为什么冻结时间仍然能证明 AC4

AC4 要证明的是「预签名地址超过 5 分钟后失效」。这件事由**服务端**判定，判定依据只有两个量：
URL 里的 `X-Amz-Date`（签名时刻）与 `X-Amz-Expires`（有效秒数），以及服务端当前时间。
服务端做的事等价于：

```
valid  <=>  signature matches  AND  now < X-Amz-Date + X-Amz-Expires
```

本单把这个判定**原样实现**在 `app/storage/signing.py` 里，并做了三件事让它成为有效证明：

1. **签名必须是真的。** `app/storage/signing.py:113-154` 用与服务端相同的 SigV4 规范
   （canonical request → string to sign → signing key → HMAC）**逐字节复算**签名，
   测试断言 `compute_signature(info, SECRET) == info.signature`，
   并断言换一把错误密钥时判定为否（`verify_presigned_url(url, "the-wrong-secret")[0] is False`）。
   这说明被判定的那把 URL，签名确实是该密钥、该对象 key、该时刻签出来的。

2. **过期窗口必须按服务端规则算。** `app/storage/signing.py:43-44` 由 `X-Amz-Date + X-Amz-Expires`
   得出过期时刻，`app/storage/signing.py:180-182` 用 `now >= expires_at` 判定失效（过期瞬间即失效，
   与 AWS 文档一致）。断言同时覆盖 **+299 秒仍有效**与**+301 秒已失效**，
   证明窗口边界正好落在 300 秒，而不是某个宽松区间。

3. **注入的过期秒数确实是参数而不是写死的常量。** `app/storage/s3_adapter.py:294-315` 的
   `expires_in` 是函数参数（默认 300），测试用 `expires_in=60` 生成另一把 URL 并断言
   `X-Amz-Expires == "60"`——如果 300 被硬编码，这个断言会失败。

换句话说：**冻结时间替换的是「服务端当前时间」这一个输入，而不是替换判定逻辑**。
判定逻辑是本单自己按服务端规范实现并被签名一致性断言约束的。
在有真 MinIO 的环境里，同样的 URL 由 MinIO 用它自己的时钟执行同一条规则。

### 5.3 在有 docker 的环境如何用真 MinIO 复核

```bash
docker compose -f deploy/docker-compose.minio.yml up -d
docker compose -f deploy/docker-compose.minio.yml logs -f minio-init

export CONTRACT_OBJECT_STORAGE_ENDPOINT=http://127.0.0.1:9000
export CONTRACT_OBJECT_STORAGE_BUCKET=contract-bucket
export CONTRACT_OBJECT_STORAGE_SECRET_KEY=minioadmin
export CONTRACT_OBJECT_STORAGE_ACCESS_KEY_ID=minioadmin

python -m pytest -q          # 同一批用例
```

`deploy/docker-compose.minio.yml` 里的 `minio-init` job 做两件幂等的事：
`mc mb --ignore-existing local/$CONTRACT_BUCKET` 与 `mc anonymous set none local/$CONTRACT_BUCKET`。
适配器侧 (`app/storage/s3_adapter.py:76-146`) 还会再执行一次
`put_bucket_acl(ACL=private)` + `put_public_access_block` + 拒绝 public ACL 的 bucket policy。

---

## 6. 逐文件用例数与耗时

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
AC1 PASS  (5 node(s), 6.72s)
=== AC2: 上传 21 MB 文件返回 413，上传 .exe 返回 415 ===
AC2 PASS  (8 node(s), 11.98s)
=== AC3: 同一文件重复上传返回 409，body 中 contract_id 与首次一致 ===
AC3 PASS  (3 node(s), 4.74s)
=== AC4: 预签名地址超过 5 分钟后失效（冻结时间的单元测试证明） ===
AC4 PASS  (5 node(s), 6.20s)
all four acceptance criteria PASS
```
