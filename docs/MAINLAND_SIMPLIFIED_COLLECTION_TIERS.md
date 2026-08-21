# 大陆标准简体包与五档采集计划

## 分包定义

InkStruct 的 9,574 字结构库被划分为两个互斥且完备的包：

- `mainland_standard_simplified_gb2312`：6,763 字；
- `non_mainland_standard_simplified`：2,811 字。

大陆标准简体包按 GB2312 可编码汉字定义。它与当前结构数据库中的 `locale=zh-Hans`
逐字完全一致，字符 SHA-256 为
`96cbde971dfde8d4650d9516dec2e98bdc7876705243e983a32967d6951ce195`。

这里的“大陆标准简体”特指 GB2312 的 6,763 个汉字，不等同于《通用规范汉字表》的
8,105 字。非大陆标准简体包包含剩余的繁体、异体、部件字和康熙部首等受支持字符。

## user_001 推荐结果

仅以 6,763 字大陆标准简体包作为生成目标和候选采集字符。当前档案的包内结构覆盖预测分
为 60.534848。

| 档位 | 目标分 | 本档新增字符 | 累计字符 | 预计达到分数 |
|---|---:|---:|---:|---:|
| 1 | 90 | 793 | 793 | 90.001749 |
| 2 | 95 | 682 | 1,475 | 95.000826 |
| 3 | 99 | 935 | 2,410 | 99.003997 |
| 4 | 99.9 | 223 | 2,633 | 99.901263 |
| 5 | 100 | 195 | 2,828 | 100.000000 |

全部 2,828 个推荐字符都属于 GB2312 包。各档 CSV 是增量文件；例如达到 99 分需要依次
完成第 1、2、3 档。预计分数假设样本通过笔顺校正、对齐和档案抽取，采集后必须重新建档
复算，不能把计划分数直接当作实测生成质量。

## 复现命令

```powershell
.\.venv\Scripts\inkstruct.exe structures export-packages `
  --database artifacts\structures\characters.sqlite3 `
  --output-dir configs\character_packages

.\.venv\Scripts\inkstruct.exe collect coverage-tiers `
  --writer user_001 `
  --index artifacts\samples_merged_202608201606\user_001\index.jsonl `
  --profile profiles\user_001\profile.json `
  --target-package mainland_standard_simplified_gb2312 `
  --output configs\collection\user_001\mainland_standard_simplified_gb2312\target_coverage_tiers_report.json
```

规划器使用加权贪心集合覆盖并逐档反向删冗余，保证每档不存在可单独删除而仍达标的字符，
但不宣称求得 NP-hard 集合覆盖问题的全局最优解。
