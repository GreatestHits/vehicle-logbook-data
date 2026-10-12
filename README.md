# vehicle-logbook-data

行车账本（DriveLedger）App 的公开数据：全国各省成品油最高零售价、调价记录、法定节假日。
由 GitHub Actions 每天北京时间 08:30、20:30 自动更新。App 经 jsDelivr / GitHub raw 只读，不含任何用户数据。
（同步到 Gitee 私有仓库仅作备份：Gitee 不允许把仓库 raw 文件当作 App 数据源。）

| 文件 | 内容 |
|---|---|
| `oil/latest.json` | 各省 92 / 95 / 98 号汽油、0 号柴油今日最高零售价（元/升） |
| `oil/history.json` | 各省各油品历次价格（生效日、价格），只在变化时追加 |
| `oil/adjustments.json` | 调价记录（窗口日、涨 / 跌 / 搁浅、汽油每吨幅度）与下次调价窗口 |
| `holiday/<年>.json` | 法定节假日与调休（来自 [holiday-cn](https://github.com/NateScarlet/holiday-cn)，MIT） |

所有文件带 `schemaVersion`、`updatedAt`。价格数据来自聚合数据"全国今日油价"接口，仅供参考，以发改委公告为准。

## 维护

- 仓库 Secrets：`JUHE_KEY`（聚合数据 Key）、`GITEE_TOKEN`（Gitee 私人令牌，同步私有备份，可选；删除即停止同步）。
- 手动运行：Actions → 更新油价数据 → Run workflow。
- 脚本源文件在主项目 `tools/data-repo/`，修改后复制到本仓库。
- 仓库长期没有提交时 GitHub 会停用定时任务；每次运行都会更新 `updatedAt` 并提交，正常不会停。
