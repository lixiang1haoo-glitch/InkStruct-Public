# InkStruct 离线采集包 v1

`.inkcapture` 是可离线传输的 ZIP，适用于 Windows 样本库，也可供后续 Android 客户端实现。文件名后缀用于打开方式。读写双方按根目录 `manifest.json` 的 `schema_version` 选择协议。v1 的版本值为 `inkstruct_capture_bundle_v1`。

## 清单和成员

清单为 UTF-8 JSON，含 `schema_version`、`writer` 和 `samples` 三个字段。

- `writer` 含 `id`、`display_name`、`scope`。它表示导出时所选的库内书写者。`w_` 加小写无连字符 UUID v4 的 ID 标记为 `portable`，其他历史 ID 标记为 `local`。显示名称只用于人工核对。
- `samples` 为 1 至 10,000 个条目的有序数组。第 0 项文件名为 `samples/00000.json`，依次使用五位十进制编号。每项含 `file`、`kind`（`han` 或 `symbol`）、`writer_id`、`sample_id`、`character`、`sha256`、`size`。
- `writer_id`、`sample_id` 和 `character` 来自该条样本 JSON。经过中转的原始样本可以保持不同于清单书写者的 ID。原始任务、采集时间、压力和点序列由样本 JSON 自身记录。汉字样本使用 `handwriting_single_v1`，标点和扩展使用 `inkstruct_symbol_sample_v1`。
- `sha256` 为样本成员未压缩原始字节的小写十六进制 SHA-256，`size` 是同一字节序列的长度。校验无需重排 JSON。ZIP 仅允许上述成员，拒绝重复文件名、未声明成员和重复原始样本身份。上限为单样本 16 MiB、全部样本 256 MiB、清单 8 MiB。

## 接收和来源

接收端先校验大小、哈希、格式和轨迹，再显示导出书写者、原书写者、目标书写者及新增、重复、冲突数量。样本身份由采集类别、原 ID 和原样本 ID 共同确定。同一身份与相同哈希重复出现时跳过，哈希相异时列为冲突并保留原样本。旧 ID 属于各自采集库，接收时应核对来源，避免把来自不同设备的同名账户当作同一人。

确认后，Windows 库保存用于采集和制包的本地归属副本，并单独保存原始字节。副本的 `writer_id` 为目标书写者，`capture.imported_from` 记录原书写者、原样本 ID、原始字节哈希，`capture.imported_task` 可记录原任务 ID。重新导出时发送原始字节。导入样本独立于采集任务进度。SHA-256 用于完整性校验，书写者归属由接收者确认。
