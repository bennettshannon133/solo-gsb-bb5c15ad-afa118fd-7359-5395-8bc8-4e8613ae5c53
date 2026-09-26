# 越野赛分段计时 API

基于 FastAPI + SQLite 的越野赛分段计时服务：

- 接收带**唯一事件号**、选手号、站点序号、发生时间的打卡；
- 支持**批量登记**（1~100 条，同一事务，批内可更正前面刚写入的记录，任一失败整体回滚）；
- 支持按事件号**更正**（新事件取代原事件）与**撤销**；
- 支持**更正预演**：试算更正前后结果，整体回滚，不产生任何副作用；
- 同一站点多条有效打卡按 (UTC 时间, 事件号) 升序取**第一条**（时间相同取事件号较小者）；
- 按站点顺序重算相邻站分段用时，**乱序补传**可填补缺段，更正 / 撤销即时更新结果；
- 相邻站缺打卡或**时间倒退**时，该分段标记为 `pending`（待定）并说明原因；
- 提供**分段入选解释**：按站点列出该选手全部打卡（事件号、时间、状态、是否入选），
  仅 `active` 参与，同站按 (UTC 时间, 事件号) 升序选一条，未入选记录说明原因
  （已更正 / 已撤销 / 较晚 / 同时间平局），并同返回按入选事件计算的现有分段，
  解释与分段基于**同一次数据库读取**；
- 提供**中立时段试算**：提交若干起止时间窗（统一转 UTC，重叠或相接的先合并），
  按各有效分段的起终打卡时间裁剪扣除暂停计时，逐段返回原始 / 扣除 / 净秒数，
  全部有效时给出净总秒数；纯试算**不写库**，不影响实时成绩与已发布版本；
- 支持**成绩发布**：在同一 SQLite 事务内读取当前打卡、按现有分段规则为所有有记录选手
  （含未完赛、保留 `pending` 分段者）生成**单调递增、不可变的版本快照**并整版原子保存；
- 已发布版本按版本号 / 最新版查询；后续打卡、更正或撤销只影响实时成绩，**不改已发布版本**；
- 提供选手分段结果查询。

## 启动

```bash
docker compose up --build
```

一条命令即可：容器启动时自动建表，数据库为空时写入示例数据（选手 R001–R006，覆盖完整成绩、乱序补传、缺站、更正、撤销、时间倒退等场景）。

- 本地端口：**8000**
- API 地址：http://localhost:8000
- 交互式文档（Swagger UI）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STATION_COUNT` | `6` | 赛道站点总数，分段为 1→2 … (N-1)→N |
| `DB_PATH` | 容器内 `/data/timing.db`，本地 `timing.db` | SQLite 数据库文件路径 |

Compose 通过命名卷 `timing-data` 持久化数据；删除卷（`docker compose down -v`）后重启会重新初始化并播种示例数据。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/checkins` | 登记打卡；携带 `corrects` 字段即为更正指定事件 |
| `POST` | `/api/checkins/batch` | 批量登记 1~100 条打卡：同一事务处理，任一失败整体回滚 |
| `POST` | `/api/checkins/preview-correction` | 预演更正：返回更正前后结果对照，整体回滚、无副作用 |
| `POST` | `/api/checkins/{event_no}/revoke` | 按事件号撤销打卡 |
| `GET` | `/api/checkins?runner_id=` | 打卡列表（含已更正 / 已撤销记录） |
| `GET` | `/api/checkins/{event_no}` | 按事件号查询单条打卡 |
| `GET` | `/api/runners/{runner_id}/splits` | 选手实时分段结果 |
| `GET` | `/api/runners/{runner_id}/splits/explain` | 分段入选解释：按站点列出全部打卡及是否入选（含原因），并返回按入选事件计算的现有分段 |
| `POST` | `/api/runners/{runner_id}/splits/neutralized` | 中立时段试算：扣除暂停计时后的净成绩，逐段返回原始 / 扣除 / 净秒数（纯试算，不写库） |
| `POST` | `/api/publications` | 发布成绩版本：同一事务读取当前打卡、整版快照原子保存，返回新版本完整成绩 |
| `GET` | `/api/publications/{version}` | 按版本号查询该版本完整成绩（不存在返回 404） |
| `GET` | `/api/publications/latest` | 查询最新发布版本完整成绩（尚未发布时返回 404） |

### 示例

登记打卡：

```bash
curl -X POST http://localhost:8000/api/checkins \
  -H 'Content-Type: application/json' \
  -d '{"event_no":"E1001","runner_id":"R100","station_seq":1,"occurred_at":"2026-09-25T08:00:00"}'
```

更正（`E1002` 取代 `E1001`）：

```bash
curl -X POST http://localhost:8000/api/checkins \
  -H 'Content-Type: application/json' \
  -d '{"event_no":"E1002","runner_id":"R100","station_seq":1,"occurred_at":"2026-09-25T08:05:00","corrects":"E1001"}'
```

批量登记（1~100 条，按顺序在同一事务内处理）：

```bash
curl -X POST http://localhost:8000/api/checkins/batch \
  -H 'Content-Type: application/json' \
  -d '{
    "checkins": [
      {"event_no":"E2001","runner_id":"R100","station_seq":1,"occurred_at":"2026-09-25T08:00:00"},
      {"event_no":"E2002X","runner_id":"R100","station_seq":2,"occurred_at":"2026-09-25T12:00:00"},
      {"event_no":"E2002","runner_id":"R100","station_seq":2,"occurred_at":"2026-09-25T08:32:00","corrects":"E2002X"},
      {"event_no":"E2003","runner_id":"R100","station_seq":3,"occurred_at":"2026-09-25T09:12:00"}
    ]
  }'
```

每条沿用单条登记的字段与校验；批内后续记录可用 `corrects` 更正**本批前面刚写入且仍有效**的事件
（上例中 `E2002` 更正同批的 `E2002X`）。全部成功时返回 `201`，携带各条事件号（按提交顺序）以及
受影响选手按现有分段规则计算的最终完成状态与总用时：

```json
{
  "results": [
    {"index": 0, "event_no": "E2001"},
    {"index": 1, "event_no": "E2002X"},
    {"index": 2, "event_no": "E2002"},
    {"index": 3, "event_no": "E2003"}
  ],
  "affected_runners": [
    {"runner_id": "R100", "complete": false, "total_seconds": null, "total": null}
  ]
}
```

任一条失败时整批回滚（新增记录与状态变更全部撤销），响应为对应语义的错误码（404 / 409 / 422），
并在 `detail.failures` 中给出失败下标（从 0 开始）与原因。前向引用（`corrects` 指向本批后面才出现
的事件，含更正自身）、批内重复事件号、无效更正（目标不存在或已失效）均按此返回：

```json
{
  "detail": {
    "message": "批量打卡在下标 2 处失败，整批已回滚",
    "failures": [
      {"index": 2, "event_no": "E2003", "reason": "事件号 E2003 与本批下标 0 重复"}
    ]
  }
}
```

预演更正（字段与正式更正相同，`corrects` 必填且须指向有效事件）：

```bash
curl -X POST http://localhost:8000/api/checkins/preview-correction \
  -H 'Content-Type: application/json' \
  -d '{"event_no":"E1002","runner_id":"R100","station_seq":1,"occurred_at":"2026-09-25T08:05:00","corrects":"E1001"}'
```

预演与正式更正使用相同的事件号唯一性、站点范围与状态校验；按现有"同站取最早 + 相邻站"规则
试算更正前后结果，返回受影响选手各自的完成状态、总用时及**仅发生变化的分段**；更正跨选手时
会同时覆盖原选手与新选手。整个预演在事务内试算后**整体回滚**：不占用事件号、不改变打卡状态
或成绩，相同请求随后可原样正式提交。响应节选：

```json
{
  "event_no": "E1002",
  "corrects": "E1001",
  "affected_runners": [
    {
      "runner_id": "R100",
      "before": {"complete": false, "total_seconds": null, "total": null},
      "after": {"complete": true, "total_seconds": 12600, "total": "3:30:00"},
      "changed_segments": [
        {
          "from_station": 1,
          "to_station": 2,
          "before": {"from_station": 1, "to_station": 2, "status": "pending", "reason": "站点 1 缺少有效打卡"},
          "after": {"from_station": 1, "to_station": 2, "status": "ok", "duration_seconds": 1920, "duration": "0:32:00"}
        }
      ]
    }
  ]
}
```

撤销：

```bash
curl -X POST http://localhost:8000/api/checkins/E1002/revoke
```

查询分段结果：

```bash
curl http://localhost:8000/api/runners/R001/splits
```

响应节选：

```json
{
  "runner_id": "R001",
  "complete": true,
  "total_seconds": 12600,
  "total": "3:30:00",
  "segments": [
    {"from_station": 1, "to_station": 2, "status": "ok", "duration_seconds": 1920, "duration": "0:32:00"},
    {"from_station": 3, "to_station": 4, "status": "pending", "reason": "站点 4 缺少有效打卡"}
  ]
}
```

## 分段入选解释

查询实时分段**采用了哪些打卡**（选手无任何打卡记录时返回 `404`）：

```bash
curl http://localhost:8000/api/runners/R004/splits/explain
```

按站点列出该选手**全部打卡**的事件号、时间、状态及是否入选；仅 `active` 打卡参与，
同一站点按 (UTC 时间, 事件号) 升序选一条，未入选记录给出原因
（`已更正` / `已撤销` / `较晚` / `同时间平局`）。响应中的 `splits` 为按这些入选事件
计算的现有分段结果，与解释基于**同一次数据库读取**，二者严格一致；更正、撤销、补传后
解释即时更新。响应节选（R004 第 2 站的错误打卡 `S-R004-2X` 已被 `S-R004-2` 更正）：

```json
{
  "runner_id": "R004",
  "station_count": 6,
  "stations": [
    {
      "station_seq": 2,
      "checkins": [
        {"event_no": "S-R004-2", "occurred_at": "2026-09-25T08:40:00Z", "status": "active", "selected": true, "reason": null},
        {"event_no": "S-R004-2X", "occurred_at": "2026-09-25T12:30:00Z", "status": "superseded", "selected": false, "reason": "已更正：被事件 S-R004-2 取代"}
      ]
    }
  ],
  "splits": {
    "runner_id": "R004",
    "complete": true,
    "total_seconds": 13680,
    "total": "3:48:00",
    "segments": [
      {"from_station": 1, "to_station": 2, "status": "ok", "duration_seconds": 2280, "duration": "0:38:00"}
    ]
  }
}
```

## 中立时段试算

赛事方可提交若干中立时段（暂停计时）的起止时间，评估扣除后的净成绩
（选手无任何打卡记录时返回 `404`）：

```bash
curl -X POST http://localhost:8000/api/runners/R001/splits/neutralized \
  -H 'Content-Type: application/json' \
  -d '{
    "windows": [
      {"start": "2026-09-25T08:10:00", "end": "2026-09-25T08:20:00"},
      {"start": "2026-09-25T16:15:00+08:00", "end": "2026-09-25T16:25:00+08:00"}
    ]
  }'
```

规则：

- 原始分段复用实时成绩的"仅有效打卡 + 同站最早入选 + 相邻站"规则，与实时分段
  基于**同一次数据库读取**生成；补传、更正、撤销后重新请求即反映最新打卡；
- 时间窗统一转 UTC（无时区按 UTC 处理，可混用带时区偏移的写法，如上例）；
  **终点不晚于起点的区间返回 `422`**；
- 重叠或相接的时间窗**先合并**，再按各有效分段的起终打卡时间**裁剪扣除**，
  跨段或重叠不会重复扣秒；响应中的 `windows` 回显合并后的 UTC 时间窗；
- 逐段返回 `raw_seconds`（原始秒数）、`deducted_seconds`（扣除秒数）、
  `net_seconds`（净秒数）；缺站或时间倒退的分段保持 `pending`，三项均为 `null`；
- 只有全部分段有效时才给出 `total_seconds` / `deducted_seconds` / `net_seconds`
  （净总秒数）与 `net`（H:MM:SS），否则均为 `null`；
- **纯试算**：不写入数据库，不改变实时成绩与已发布版本。

响应节选（上例两个时间窗合并为 08:10–08:25 UTC，落在分段 1→2 内）：

```json
{
  "runner_id": "R001",
  "station_count": 6,
  "complete": true,
  "windows": [
    {"start": "2026-09-25T08:10:00Z", "end": "2026-09-25T08:25:00Z"}
  ],
  "segments": [
    {"from_station": 1, "to_station": 2, "status": "ok", "raw_seconds": 1920, "deducted_seconds": 900, "net_seconds": 1020},
    {"from_station": 2, "to_station": 3, "status": "ok", "raw_seconds": 2400, "deducted_seconds": 0, "net_seconds": 2400}
  ],
  "total_seconds": 12600,
  "deducted_seconds": 900,
  "net_seconds": 11700,
  "net": "3:15:00"
}
```

## 成绩发布与版本查询

发布（无需请求体）：在**同一 SQLite 事务**内先取得写锁再读取全部当前打卡，按现有分段规则
（同站取最早、相邻站重算、缺站 / 时间倒退为 `pending`）为**所有有打卡记录的选手**生成完整成绩，
版本号从 1 起单调递增，版本头与全体选手快照原子提交：

```bash
curl -X POST http://localhost:8000/api/publications
```

```json
{
  "version": 1,
  "published_at": "2026-09-25T03:00:00+00:00",
  "station_count": 6,
  "results": [
    {
      "runner_id": "R001",
      "station_count": 6,
      "complete": true,
      "total_seconds": 12600,
      "total": "3:30:00",
      "stations": [
        {"station_seq": 1, "event_no": "S-R001-1", "occurred_at": "2026-09-25T08:00:00+00:00"}
      ],
      "segments": [
        {"from_station": 1, "to_station": 2, "status": "ok", "duration_seconds": 1920, "duration": "0:32:00"}
      ]
    },
    {
      "runner_id": "R003",
      "complete": false,
      "total_seconds": null,
      "total": null,
      "segments": [
        {"from_station": 3, "to_station": 4, "status": "pending", "reason": "站点 4 缺少有效打卡"}
      ]
    }
  ]
}
```

- 未完赛选手同样出现在 `results` 中并保留各自的 `pending` 分段（如上例 R003）；
- 发布事务先取写锁，**并发的打卡 / 更正 / 撤销会被阻塞至本次发布完成**，因此同一版本的全部
  选手成绩来自同一个提交时点，不会混入不同时间点的数据（连接设置了 5 秒 `busy_timeout`）。

按版本号查询完整成绩：

```bash
curl http://localhost:8000/api/publications/1
```

查询最新版本（尚未发布过任何版本时返回 `404`；指定版本不存在同样返回 `404`）：

```bash
curl http://localhost:8000/api/publications/latest
```

**已发布版本不可变**：发布之后新的打卡、更正或撤销只影响实时成绩
（`GET /api/runners/{id}/splits`），不会改动任何已发布版本；再次调用
`POST /api/publications` 才会生成下一个版本号（2、3、…）：

```bash
# 发布 v1 后撤销 R001 的第 6 站并补传新打卡
curl -X POST http://localhost:8000/api/checkins/S-R001-6/revoke
curl -X POST http://localhost:8000/api/checkins \
  -H 'Content-Type: application/json' \
  -d '{"event_no":"E3001","runner_id":"R001","station_seq":6,"occurred_at":"2026-09-25T11:35:00"}'

curl -X POST http://localhost:8000/api/publications   # -> version 2，反映新实时成绩
curl http://localhost:8000/api/publications/1         # 仍是发布时的 v1 快照
curl http://localhost:8000/api/publications/latest    # -> version 2
```

## 本地开发

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload        # 默认监听 8000 端口
pytest                               # 运行测试
```

## 实现说明

- 打卡记录永久保留，更正 / 撤销只改变状态（`active` / `superseded` / `revoked`），便于审计；
- 分段结果在查询时基于全部有效打卡实时重算，因此补传、更正、撤销立即反映到结果中；
- 分段入选解释与分段结果共用同一套"同站按 (UTC 时间, 事件号) 升序选一条有效打卡"的规则，
  并在**同一次数据库读取**上推导：先一次查询取出该选手全部打卡（含已更正 / 已撤销），
  再据此给出每条记录的入选情况与原因、计算现有分段，二者严格一致；
- 时间统一归一化为 UTC 存储，无时区的时间按 UTC 处理；
- 更正与写入在同一事务中完成，事件号唯一性由数据库主键保证（重复返回 409）；
- 批量登记在同一数据库事务内按顺序处理全部记录，任一失败即整体回滚（含已做的状态变更），
  成功时基于全部新数据按现有分段规则重算受影响选手的最终完成状态与总用时；
- 更正预演复用正式更正的校验与写入逻辑，在 `SAVEPOINT` 内试算后 `ROLLBACK TO` 整体回滚，对数据库零副作用；
- 中立时段试算与实时分段共用"同站最早入选 + 相邻站重算"规则并在同一次读取上推导；
  时间窗统一转 UTC 后先合并重叠 / 相接区间，再与各有效分段的 [起, 终] 区间求交集扣除，
  合并后的窗口互不重叠、每段独立裁剪，因此跨段或重叠不会重复扣秒；试算只读不写，
  不影响实时成绩与已发布版本；
- 成绩发布在 `BEGIN IMMEDIATE` 事务内"先取写锁、再读全部打卡"，版本头（`publications`，
  `INTEGER PRIMARY KEY AUTOINCREMENT` 保证版本号单调递增、不重用）与全体选手快照
  （`publication_entries`，逐选手 `SplitsOut` JSON）在同一事务内原子提交；持锁期间并发打卡 /
  更正 / 撤销一律阻塞（配合 `busy_timeout`），同一版本不会混入不同时间点的数据；
- 已发布版本是独立于 `checkins` 实时表的快照，后续打卡 / 更正 / 撤销不会改写历史版本。
