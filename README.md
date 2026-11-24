# 会员空间平台 · 合同文件上传接口与私有对象存储写入

订单 1899 /【S5-DOC-003】交付代码。

两个接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/doc/contracts` | multipart 上传单文件（PDF / DOCX / JPG / PNG，≤ 20 MB），返回 `{contract_id, status}` |
| GET | `/api/doc/contracts/{contract_id}/file` | 返回 5 分钟有效的预签名下载地址，返回 `{url, expires_at}` |

错误码：`413` 超限、`415` 类型不支持、`409` 重复、`403` 无权限、`404` 不存在或不属于本组织。

---

## 1. 运行方式

### 1.1 环境

- Python 3.11+（本机实测 3.11.9）
- 依赖：`requirements.txt`（运行时）/ `requirements-dev.txt`（测试）
- 数据库：默认 SQLite（PostgreSQL 16 亦可，见 1.4）
- 对象存储：S3 兼容（MinIO / AWS S3），端点由环境变量指定

### 1.2 安装

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
pip install -r requirements-dev.txt
```

### 1.3 环境变量（只从环境变量读取，缺失或空串在启动期直接抛错）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `CONTRACT_OBJECT_STORAGE_ENDPOINT` | **是** | - | S3 兼容端点，如 `http://127.0.0.1:9000` |
| `CONTRACT_OBJECT_STORAGE_BUCKET` | **是** | - | 私有桶名 |
| `CONTRACT_OBJECT_STORAGE_SECRET_KEY` | **是** | - | 密钥 |
| `CONTRACT_OBJECT_STORAGE_ACCESS_KEY_ID` | 否 | `minioadmin` | 访问键 |
| `CONTRACT_OBJECT_STORAGE_REGION` | 否 | `us-east-1` | 区域 |
| `CONTRACT_DATABASE_URL` | 否 | `sqlite:///./contracts.db` | 数据库连接串 |
| `CONTRACT_SITE_TIMEZONE` | 否 | `Asia/Shanghai` | **站点时区**，决定 key 的 yyyy/mm |
| `CONTRACT_MAX_FILE_SIZE_BYTES` | 否 | `20971520` | 单文件上限 |
| `CONTRACT_PRESIGN_TTL_SECONDS` | 否 | `300` | 预签名有效期 |

```bash
export CONTRACT_OBJECT_STORAGE_ENDPOINT=http://127.0.0.1:9000
export CONTRACT_OBJECT_STORAGE_BUCKET=contract-bucket
export CONTRACT_OBJECT_STORAGE_SECRET_KEY=minioadmin
```

三项中任何一项缺失、为空串或全为空格，`app.config.load_settings()` 抛 `ConfigurationError`，
应用在**启动期**（lifespan 内）终止，绝不退化成运行期 500。

### 1.4 建库（两种方式）

```bash
# 方式一：Alembic 迁移（推荐，含部分唯一索引）
export CONTRACT_DATABASE_URL=sqlite:///./contracts.db
alembic upgrade head

# 方式二：应用启动时自动建表（仅开发用）
# app.main.create_app() 的 lifespan 会调用 Base.metadata.create_all()
```

迁移生成的索引（SQLite 与 PostgreSQL 均可创建）：

```sql
CREATE UNIQUE INDEX uq_doc_contract_org_sha256_active
  ON doc_contract (org_id, sha256) WHERE deleted_at IS NULL;
```

PostgreSQL 16：把 `CONTRACT_DATABASE_URL` 换成 `postgresql+psycopg://user:pass@host/db` 即可。
本单不涉及 pgvector，也不使用 PostgreSQL 专有类型；唯一索引是标准 SQL 的部分索引，
SQLite 与 PostgreSQL 语义一致。**本机没有 PostgreSQL**，交付实测用 SQLite 完成。

### 1.5 启动

```bash
# 初始化私有桶（幂等）
python -m app.cli

# 起服务
uvicorn app.main:get_app --factory --host 127.0.0.1 --port 8000
```

### 1.6 跑测试与 OpenAPI 断言

```bash
python -m pytest -q                  # 全量用例
python scripts/check_openapi.py      # OpenAPI 断言，退出码 0/1
```

---

## 2. 运行环境边界（重要，请先读）

**交付机器上没有 docker、没有 MinIO 服务端、没有 PostgreSQL。** 因此：

| 承诺 | 本机实际做法 |
|---|---|
| 「测试连真 MinIO」 | 本机**不可能**起真 MinIO。改为用 **moto 的 `ThreadedMotoServer`**——一个真正的 HTTP 服务器，boto3 通过**真实 HTTP 协议栈**（SigV4 签名、multipart 上传、预签名 URL）访问它，不是进程内拦截的 `mock_aws` 装饰器。 |
| `deploy/docker-compose.minio.yml` | **作为交付物提供，本机从未运行过**（无 docker）。文件头已写明这一点。文件内含 MinIO 服务 + 幂等初始化 job（建桶 + `mc anonymous set none` 私有策略），在有 docker 的主机上 `docker compose -f deploy/docker-compose.minio.yml up -d` 即可起真 MinIO。 |
| 数据库 | SQLite（SQLAlchemy 2 + Alembic）。PostgreSQL 16 的连接串已支持，但本机无 PostgreSQL，未实测。 |
| AC4 预签名过期 | moto **不校验预签名过期**（实测：`ExpiresIn=1` 的 URL 放 2.5 秒后 GET 仍返回 200）。因此 AC4 由 `app/storage/signing.py` 中**自研的 SigV4 校验器**按服务端同规则判定（复算签名 + 过期窗口），并直接断言 URL 里的 `X-Amz-Date` / `X-Amz-Expires`。校验器已验证与 boto3 生成的签名**逐字节一致**。服务端时钟篡改在本地无法模拟，这一点如实写明。 |
| freezegun 的作用 | 冻结**应用侧**时钟，使 `expires_at`、key 的 yyyy/mm 与过期边界判定可复现；**不**用于模拟 MinIO 服务端时钟。 |
| moto 的作用 | 提供 S3 协议实现：桶、对象、multipart、预签名、私有 ACL / 匿名 GET 403。 |

---

## 3. 十个关键设计点（对应提案承诺）

### 3.1 格式双判：扩展名白名单 + magic number

`app/doc/types.py`。扩展名来自文件名（白名单 pdf/docx/jpg/png），真实类型来自前若干字节：

| 格式 | magic number |
|---|---|
| PDF | `%PDF-` |
| DOCX | ZIP 的 `PK` 三字节 **且** 含 `[Content_Types].xml` |
| JPG | `FF D8 FF` |
| PNG | `89 50 4E 47 0D 0A 1A 0A` |

**不一致时以真实类型为准并拒绝（415）**：`.exe` 改名 `.pdf` → 415；PDF 内容配 `.png` 后缀 → 415。
扩展名不在白名单 → 415（连文件都不用读）。

### 3.2 流式累计 + 413 清理

`app/doc/streaming.py`。按 **1 MB** 分块读，边读边更新 sha256 与累计 size，**不信 `Content-Length`**
（该头可撒谎，也可缺失）。累计超过上限立刻中止：

- 写入侧使用 S3 **multipart upload**，中止 = `abort_multipart_upload`，已写分片全部消失；
- 因此 413 之后**桶内既没有半个对象，也没有 pending multipart**。

### 3.3 查重与唯一索引（带软删）

`app/doc/service.py` + `migrations/versions/0001_init.py`。

顺序是硬性的：**读完先查 `(org_id, sha256, deleted_at IS NULL)` → 命中返 409 且 body 带既有 `contract_id`；
未命中才写最终 key 并建 `doc_contract`（`status=uploaded`）**。

唯一索引 `(org_id, sha256) WHERE deleted_at IS NULL` ⇒ 软删后同文件**可以**重传，且拿到**新 id**。
查重命中时不会在桶里留下孤儿对象（对象此时尚未完成提交）。

### 3.4 key 规则与站点时区

`app/doc/keys.py`，**纯函数** `contracts/{org_id}/{yyyy}/{mm}/{uuid4}.{ext}`：

- `yyyy`/`mm` 取**站点时区**（`CONTRACT_SITE_TIMEZONE`，默认 `Asia/Shanghai`），可注入时刻；
- `uuid4` ⇒ 不可枚举、1000 次生成零重复；
- `ext` 来自**白名单映射**，绝不由文件名切割而来 ⇒ `../../x.pdf` 无法影响 key。

### 3.5 预签名：过期秒数参数注入

`app/storage/s3_adapter.py: presigned_get_url(key, expires_in=300, now=None)`。
`expires_in` 是参数（默认 300），`now` 可注入时钟。`expires_at` 由**同一时钟**算出。
AC4 断言：`X-Amz-Expires == 300`、`expires_at == 注入时刻 + 300`、+299 s 仍有效 / +301 s 已失效。

### 3.6 私有桶 + 响应键集合

`app/storage/s3_adapter.py: ensure_bucket()` 幂等地把桶设为私有：

1. `put_bucket_acl(ACL=private)`；
2. `put_public_access_block`（Block/Ignore/Restrict 全部 True）；
3. bucket policy 拒绝任何 `s3:PutObjectAcl` 且 `x-amz-acl` 为 `public-read` / `public-read-write` 的请求。

> 实现说明：策略**不**使用 `Deny` + `s3:GetObject`。moto 会**强制执行**策略，把
> `DenyInsecureTransport` 这类语句作用到纯 HTTP 上，会把合法的签名写请求打成 403；
> `Deny s3:GetObject` 则会连带打掉合法的预签名下载。私有性由 `private` ACL 与 public access block 保证。

响应体键集合上限两键：上传**恰 2 键** `contract_id` / `status`；下载**恰 2 键** `url` / `expires_at`。
不返回任何对象直链或 bucket URL。

### 3.7 环境变量必填且拒空串

`app/config.py`。三项必填，**空串与缺失同样在启动期抛 `ConfigurationError`**。

### 3.8 投递失败语义

`app/doc/dispatch.py`。语义明确写死为：**先落记录，再投递；投递失败不回滚上传**。

- 记录与 outbox 行先写；
- 投递走识别任务队列的**桩**（`RecognitionDispatcher`）；
- 桩抛错 ⇒ 记录转 `dispatch_pending`，接口**仍返 201**；
- outbox 行幂等键 = `(contract_id, dispatch_version)` ⇒ `contract_id:1`；
- 重试成功后 outbox 置 `sent`，**任务表恰 1 行**（`doc_recognition_task.contract_id` 唯一）。

### 3.9 权限：404 与 403 的分界

`app/doc/service.py: presign_download`。**先按 `(id, org_id)` 收窄 → 404**，再判角色 → 403。
跨组织访问与随机 id 的 404 响应**逐字节相同**（同状态码、同 body、同 content-type），
无法通过枚举 id 探测他组织数据。

### 3.10 multipart 文件名处理

只取路径最后一段作展示名；**扩展名从白名单映射取**，不拼进对象键。
非 ASCII 文件名（中文）可正常上传，key 仍为纯 ASCII。

---

## 4. AC1–AC4 逐条复现

### AC1 · 四种允许格式均 201，且 MinIO 中能看到对象

```bash
python -m pytest -q tests/test_ac1_formats.py
```

应看到：`5 passed`（4 个格式参数化 + 桶非 public-read 断言）。

每个参数化用例都断言：HTTP 201、响应体恰 2 键、**桶内新增对象恰 1 个**、
key 匹配 `contracts/{org}/{yyyy}/{mm}/{uuid4}.{ext}`、`head_object` 的 `ContentLength` 等于文件字节数。

证据文件：`docs/checks/pytest.log`

### AC2 · 21 MB 返 413，.exe 返 415

```bash
python -m pytest -q tests/test_ac2_limits.py
```

应看到：`10 passed`。含 21 MB→413、.exe→415、.exe 改名 .pdf→415、PDF 配 .png→415、
恰好 20 MB→201、20 MB+1 B→413、`Content-Length` 撒谎→413、413 后桶内 0 对象 0 pending multipart。

证据文件：`docs/checks/pytest.log`

### AC3 · 重复上传返 409，body 的 contract_id 与首次一致

```bash
python -m pytest -q tests/test_ac3_duplicates.py
```

应看到：`3 passed`。断言 409 的 `contract_id` 等于首次的 id、**库中记录数恰 1**、桶内对象数不增加、
软删后重传 201 且新 id 不同、他组织可上传同一文件。

证据文件：`docs/checks/pytest.log`

### AC4 · 预签名地址超过 5 分钟后失效

```bash
python -m pytest -q tests/test_ac4_presign.py
```

应看到：`5 passed`。断言 `X-Amz-Expires == 300`、`expires_at == 注入时刻 + 300`、
**+299 s 仍有效 / +301 s 已失效**、自研 SigV4 复算与 boto3 签名一致、错密钥判否。

证据文件：`docs/checks/pytest.log`、`docs/checks/openapi.log`

### 附加：并发、权限、配置、key、投递、文件名

```bash
python -m pytest -q tests/test_concurrency.py tests/test_permissions.py \
                  tests/test_config.py tests/test_keys.py \
                  tests/test_dispatch.py tests/test_filename_handling.py
```

应看到：`22 passed`。其中 10 并发同文件 ⇒ **1 条 201 + 9 条 409**，库中记录数 1，桶内对象数 1。

---

## 5. 目录结构

```
app/
  config.py              # 环境变量配置模型（三项必填、拒空串）
  auth.py                # 身份与角色（S2-IAM 的桩）
  db.py  models.py       # SQLAlchemy 2 引擎与会话 / ORM 模型
  deps.py                # FastAPI 依赖
  main.py  cli.py        # 应用工厂 / 桶初始化 CLI
  storage/
    s3_adapter.py        # S3 兼容适配器（私有桶、multipart、预签名）
    signing.py           # SigV4 预签名校验器（AC4 的过期判定）
  doc/
    keys.py              # key 纯函数
    types.py             # 格式双判（扩展名 + magic number）
    streaming.py         # 流式 sha256/size 累计与 multipart 中止
    dispatch.py          # 识别任务投递桩 + outbox
    service.py           # 上传/下载业务逻辑
    api/contracts.py     # 两个 HTTP 接口
migrations/              # Alembic（部分唯一索引）
scripts/check_openapi.py # OpenAPI 断言脚本
deploy/docker-compose.minio.yml  # MinIO + 私有桶初始化 job（本机未运行）
tests/                   # pytest 用例
docs/checks/             # 交付证据（pytest.log / openapi.log / env.log ...）
```

---

## 6. 不在本次范围内（提案 exclusions）

不做合同文本识别与字段抽取；不做识别任务队列本身（用桩）；不做前端上传组件；
不做 S2-IAM 实现（用 mock）；不做文件版本替换与历史；不做批量上传与压缩包；
不做对象存储生命周期与归档；不做病毒扫描；不做跨区域复制。
