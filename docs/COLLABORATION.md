# InkStruct GitHub 协作与环境准备

主仓库 [InkStruct](https://github.com/lixiang1haoo-glitch/InkStruct) 维护生成与桌面、字集研究与评测、公共协议。移动端位于私有仓库 [InkStruct-Android](https://github.com/lixiang1haoo-glitch/InkStruct-Android)。两组按[任务书](team_tasks_20261022/组长准备与协作清单.md)推进；组长负责主线集成和写字机。

## 获取协作基线

迁移 PR 合并前，克隆后检出 `codex/team-baseline-20261022`。该分支在原远端历史之上保留本地开发历史，再加入当前 0.1.40 工作树；原 main 和用户数据不被替换。不要只用旧 main 的文件开始开发。

```powershell
git clone --recurse-submodules https://github.com/lixiang1haoo-glitch/InkStruct.git
cd InkStruct
git switch codex/team-baseline-20261022
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[desktop,dev]"
```

Python 支持 3.12 至 3.13，推荐该基线使用 3.13。桌面不要求 GPU／PyTorch；训练 extras 为独立研究用途。macOS 使用对应的 `.venv/bin/python`；成员保留自己的环境，不复制组长虚拟环境。

## 资源与依赖

| 项目 | 获取与身份 | 是否在 Git 中 |
| --- | --- | --- |
| Make Me a Hanzi | `git submodule update --init --recursive`，固定提交 `bddc96d41bef78427ed0e034e9f7e31d71fd1b92`，保留 APL／LGPL | 只有 gitlink，内容从上游获取 |
| 结构数据库 | 执行下列 structures build；使用修正规则时校验实际资源身份 | 被忽略，可从固定源重建 |
| 完整具名字表 | `configs/character_sets/`，应用校验固定哈希 | 包含事实数据、许可证与来源 |
| 桌面采集内核 | 组长提供 `InkStruct-collector-kernel-source-20261022.zip`，用校验脚本安装 | 仅提交哈希清单，不含源包 |
| 研究作者样本与验证集 | 组长按授权范围单独分发；字集组冻结划分并重新建档 | 不提交 |
| 生成结果、评分和字体 | 每次新目录，记录版本与输入身份 | 不提交 |

```powershell
.venv/Scripts/python.exe -m inkstruct.cli structures build
.venv/Scripts/python.exe scripts/install_collector_source.py "C:/path/to/InkStruct-collector-kernel-source-20261022.zip"
.venv/Scripts/python.exe -B -m inkstruct.application --workspace workspaces/team
```

安装脚本核验整包与逐文件哈希，只写入尚不存在的 `artifacts/external/data_collection`，已有目录不会覆盖。外部包是采集源代码与既有参考资源，不包含作者轨迹；原来源及许可声明保留，不在本迁移中重新授权。缺少源包时可以运行不依赖采集器的基础测试，集成采集验收须等待资源齐备。

## 任务和接口

- 字集组：[研究与评测任务书](team_tasks_20261022/字集研究与评测组任务书.md)。
- Android 组：[开发任务书](team_tasks_20261022/Android开发组任务书.md)。
- 双方共同维护：[接口与验收约定](team_tasks_20261022/共用接口与验收约定.md)。其中新增任务与批次格式需 M0 联调实现，不能假定现有程序已支持。

Android 的接口引用此仓库的固定提交与文件哈希，不维护第二份可独立变更的正式协议。新增接口先提交主仓库 PR，标明 Android 兼容改动。应用版本仍从 `src/inkstruct/fonts/__init__.py` 读取；新构建由组长分配版本。

## 基础检查与证据

基础 CI 不读取真实作者档案，涵盖字表、目标、批次分组、推荐与语义准入。完整 Qt、建档和生成、样本质量、Android 真机、写字机分别验收。历史报告只表示当时的输入与版本。

```powershell
.venv/Scripts/python.exe scripts/check_repository_hygiene.py
.venv/Scripts/python.exe -B -m pytest tests/test_character_sets.py tests/test_generation_targets.py tests/test_collection_receipt.py tests/test_recommend.py tests/test_v61_starter_collection.py tests/test_v62_semantics.py -p no:cacheprovider
```

Issue 记录负责人、阶段、依赖和验收标准；PR 写清行为与证据。组长账号为 `lixiang1haoo-glitch`，其余成员尚待登记，不虚构账号或自动发送邀请。主分支保护由组长按账号功能设置；本提交不修改权限或付费配置。
