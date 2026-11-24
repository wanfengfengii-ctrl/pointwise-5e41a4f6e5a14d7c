# 限披露站件交班

白班按冻结修订签发。夜班决定实际采用的来件及查询。两边通过固定站件文本交接，核定库独立于录制库和发件库。V1 的入口及原成果格式见 README.md。

## 调用

| 入口 | 结果 |
| --- | --- |
| `exchange.issue_public(store, catalog, revision_id)` | 签发 V2 固定站件，返回 `SuccessReceipt`。用 `archive.fetch(catalog, receipt.artifact_id).payload` 取发件文本。 |
| `review.audit_mixed(catalog, packages, queries)` | `packages` 为所选 V1 或 V2 JSON 文本的集合或序列，`queries` 为有序同步标识对，查询参数沿用 `review.audit`。返回 `(report, receipt)`，其中 `report` 是与归档 JSON 正文对应的字典，`receipt` 是 `SuccessReceipt`。 |
| `archive.fetch(catalog, artifact_id)` | 领取已签站件或报告的固定正文与成功回执。 |

只依据指定冻结修订发行，先核查整站约束。格式合法的录制中，任何连通片矛盾都须阻止签发。沿用 `UnknownRevision` 和 `InconsistentConstraints`。

## V2 站件

固定 JSON 保留 V1 外层的 `version`、`package_id`、`origin`、`evidence` 四个字段。版本为整数 `2`，冻结出处 `origin` 仍由 `station`、`recording`、`revision` 组成。下列为字段示例。

```json
{
  "version": 2,
  "package_id": "pkg-example",
  "origin": {"station": "example", "recording": "shift", "revision": "r1"},
  "evidence": {
    "public": ["P", "Q", "I"],
    "bounds": [
      {"start": "P", "end": "Q", "upper_us": -2, "refs": ["observation-7"]}
    ]
  }
}
```

`public` 列出该修订的全部公开同步标识，各出现一次，包括孤立点。`bounds` 每行的 `start`、`end` 为已声明的不同公开同步标识，每个有向点对至多一行。`upper_us` 是精确整数微秒，允许零和负数，布尔值无效。`refs` 是非空的有序原比较编号数组，统一使用件的冻结出处。每行的界值是这些原比较从起点到终点依次接续的权重和。接收方可在公开点把多行约束共同用于核定，无可达关系的点对可以没有行。没有公开点的可行修订可发空的 `public` 和 `bounds`。沿用 V1 的标识校验和精确整数语义。

新件只披露公开同步标识、公开点间约束和冻结出处下的原比较编号。编号按原样交付，接收方将其视为不透明引用。私有脉冲、私有端点及相关原比较的逐边权重留站。夜班以通过格式和绑定校验的签发件为供数依据。

## 混收裁决和报告

新旧件按相同的公开同步标识接续。V1 私有点沿用原冻结出处与局部名的作用域。以完整原据为口径时，每项查询先取最紧的有向上界，再在同界路径中取原比较条数最少的，最后比较整条引用序列的字典序。序列中每项按 `(station, recording, revision, id)` 比较。有向不可达记 `null`，同点记 `0`，二者的引用均为空。不同点间的零界保留实际引用。整单共同可行性包含查询未涉及的比较，空查询照常裁决。

非法站件、同号异文、同一冻结出处对应不同事实或同时提交该出处的 V1 与 V2 均抛出 `exchange.InvalidPackage`。对象字段顺序及站件事实列表顺序不影响同文判断，`refs` 的次序属于事实。同号同文的重投只接纳一次。同源同版本且事实相同的不同件号各自保留。非法查询或未知公开同步点抛出 `review.UnknownQueryEndpoint`，整单矛盾抛出 `station.InconsistentConstraints`。

报告正文的顶层键为 `version`（整数 `2`）、`report_id`、`package_ids` 和 `results`。`report_id` 与成功回执中的 `artifact_id` 一致。`package_ids` 按实收件号排序。`results` 逐项记录 `position`（从零计数）、`start`、`end`、`upper_us` 和 `witness`，保留原查询顺序和重复项。`witness` 为有序数组，每项仅含 `origin` 和原比较 `id`，V1 提供的比较也按此形状报告。报告与成功回执同次提交，拒签或提交失败均无本次新增。写入或提交被拒沿用 `archive.PublicationError`。

## 样例与运行

`public_handoff_sample.py` 提供冻结录制用的原始输入。运行 `python3 -B public_handoff_sample.py` 可以看到完整 V1 原据的对照结果。

- 用甲 `ALPHA` 签 V2、乙 `BETA` 签 V1。只收甲时，S→U 为 3，引用 a1、a2、a3，U→S 与 S→I 不可达，I→I 为零。混收后，S→U 仍为 3，引用按序为乙的 b2、甲的 a3。件序颠倒、同件重投和查询重复均保留正确结果及查询位置。
- 再收丙 `GAMMA`，U→S 的 −4 令整单矛盾，空查询也须拒签。
- 用 `PREFIX_ALPHA` 签 V2、`PREFIX_BETA` 签 V1。S→D 的两条最紧链均为 2 微秒、三条原比较，且共用首条 a1。正确引用为 a1、a2、b2。

保留原回归及演示。将新链路接入 `.pointwise-runtime.json`。该清单采用版本 `1` 和 `cli` 类型，`setup` 是准备命令的参数数组列表，可为空，`verify` 和 `demo` 各为一个命令的参数数组。核验覆盖限披露、混收和选证、空查询矛盾、冲突拒收、签存失败无新增以及重开领回，失败时退出非零。演示应在关闭录制库后实际混收、核账并重开成果库领取报告与回执。
