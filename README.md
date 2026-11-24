# 河口计量联合实验室离线复核 V1

白班设备员把脉冲比测录制交给登记岗。核账员按录制修订核对时差上界和原比较，签发岗把指定修订制成固定站件。夜班在隔离成果库中，仅用交班员提供的站件复核有序查询。设备勘误产生新修订，次日值班员仍可按同一成果号领取旧站件、旧报告和回执。

## 运行

使用 Python 3.11 标准库。从工程根目录运行正常回归和演示。

```sh
python3 -B check_project.py
python3 -B demo_shift.py
```

控制台提供 `check_project.py`。直接运行完整原套件也可使用 `python3 -B -m unittest discover -s tests -t . -v`。演示在独立临时目录内建立录制库、站件成果库和夜班成果库，完成后释放这些数据库。

## Python 接口

| 接口 | 输入与结果 |
| --- | --- |
| `record.RevisionStore(path)` | 打开录制库并初始化，可用作上下文管理器。`get(revision_id)` 读取指定不可变快照。 |
| `record.freeze(store, station, recording, pulses, comparisons, *, supersedes=None)` | 校验并追加整份录制，返回修订号。勘误以 `supersedes` 引用同一站点、同一录制的既有修订。 |
| `station.account(store, revision_id, start, end)` | 使用该修订中的公开局部名，返回 `StationAccount`，其中 `upper_us` 为整数或 `None`，`witness` 为可核对的原比较边。 |
| `archive.ArtifactCatalog(path)` | 打开成果库并初始化，可用作上下文管理器。录制库和成果库均可重复调用 `initialize()`，保留已提交数据。 |
| `exchange.issue(store, catalog, revision_id)` | 签发指定修订，返回成功回执，`artifact_id` 即站件号。 |
| `exchange.receive(payload)` | 从固定站件 JSON 文本校验并读取只读证据，本站和外站采用同一格式。 |
| `review.audit(catalog, packages, queries)` | 接收固定站件 JSON 文本序列和 `(起点同步标识, 终点同步标识)` 查询序列，返回 `(AuditReport, SuccessReceipt)`。空查询仍做整单裁决。 |
| `archive.fetch(catalog, artifact_id)` | 返回 `ArchivedArtifact`，含固定 JSON 文本 `payload` 和 `receipt`。读取使用持久化内容。 |

脉冲声明的 `name` 是录制内唯一的局部名。`sync` 为非空同步标识时表示公开脉冲，为 `None` 时表示临时脉冲。同一修订中每个同步标识登记一次。标识为非空 Unicode 字符串，禁止首尾空白和空字符。每条比较的 `id` 在本修订内唯一，`start`、`end` 都须已登记，`unit` 须为 `us`，`upper_us` 须为整数。每条比较 `u→v` 的含义为 `t(v) − t(u) ≤ upper_us`，零和负数有效。

```python
from archive import ArtifactCatalog, fetch
from exchange import issue
from record import RevisionStore, freeze
from review import audit
from station import account

pulses = [
    {"name": "s", "sync": "S"},
    {"name": "h", "sync": None},
    {"name": "t", "sync": "T"},
]
comparisons = [
    {"id": "a1", "start": "s", "end": "h", "upper_us": 0, "unit": "us"},
    {"id": "a2", "start": "h", "end": "t", "upper_us": 5, "unit": "us"},
]
with RevisionStore("recordings.sqlite") as source, ArtifactCatalog("stations.sqlite") as outgoing:
    revision = freeze(source, "alpha", "shift-1", pulses, comparisons)
    balance = account(source, revision, "s", "t")
    assert balance.upper_us == 5
    receipt = issue(source, outgoing, revision)
    package = fetch(outgoing, receipt.artifact_id).payload

with ArtifactCatalog("night.sqlite") as incoming:
    report, receipt = audit(incoming, [package], [("S", "T"), ("T", "S")])
    assert [result.upper_us for result in report.results] == [5, None]
    saved_report = fetch(incoming, receipt.artifact_id)
```

## 固定数据与裁决

V1 站件 JSON 由 `version`、`package_id`、`origin`、`evidence` 组成。`version` 为整数 `1`。`origin` 包含 `station`、`recording`、`revision`，`evidence` 内含相同的 `origin`、`pulses` 和 `comparisons`。外站可以按该形状独立制件。只含直接公开比较且确实没有其他原比较的旧件也遵循该形状。重复提供同一号、同一事实的站件只接纳一次。同号件的来源或同一冻结来源的完整证据互相冲突时拒绝收件。报告的 `package_ids` 按编号排序，`results` 按查询出现顺序保存。

不同件的公开脉冲按 `sync` 接续。暂存脉冲按冻结来源及局部名解释。比较方向和编号保留原样，报告每条凭据中的 `origin` 与 `id` 共同定位原比较。沿链核对时，同一录制内的局部端点可以直接接续，跨录制需用站件的公开同步声明核对。共同可行时，有向最短路径权重就是精确上界。等长链优先取边数少的链，同步数时按冻结来源、证据编号顺序选择。零权环不会进入见证。已知但不可达返回 `None`，JSON 中为 `null`。同一图点间的上界为零、证据链为空。不同图点间的零界附原比较链。

非法录入抛出 `ValueError`，格式合法的矛盾录制仍可冻结。未知修订抛出 `record.UnknownRevision`，站内或整单矛盾抛出 `station.InconsistentConstraints`，非法站件抛出 `exchange.InvalidPackage`，复核查询格式错误或未知同步点抛出 `review.UnknownQueryEndpoint`。非法局部查询点抛出 `ValueError`。发布写入或提交失败抛出 `archive.PublicationError`，本次载荷和成功回执全部回滚。未知成果号抛出 `archive.ArtifactNotFound`，成果存在而回执缺失或配对无效时抛出 `archive.ArchiveIntegrityError`。

## 核对样例

甲站的 `S→h→T` 分别为 0 和 5 微秒。乙站仍有自己的 `h`，它给出的 `T→h→S` 权重为 1 和 −2，同时给出 `T→U` 权重 2。甲、乙的 `T` 局部名不同，同步标识相同。两站可共同签收，`U−S` 上界为 7，`S−T` 上界为 −1。另交丙站 `U→S` 权重 −8 的站件，三站闭环要求 `0≤−1`，整单拒签。原回归还核对断开查询、重复位置、两站同号原凭据、勘误后指定旧修订签发、重开领取，以及SQLite 延迟外键触发的提交失败回滚。
