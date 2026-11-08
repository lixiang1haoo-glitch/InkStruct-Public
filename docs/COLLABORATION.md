# InkStruct GitHub 协作与环境准备

主仓库 [InkStruct](https://github.com/lixiang1haoo-glitch/InkStruct) 维护生成与桌面、字集研究与评测、公共协议。移动端位于私有仓库 [InkStruct-Android](https://github.com/lixiang1haoo-glitch/InkStruct-Android)。两组按[任务书](team_tasks_20261022/组长准备与协作清单.md)推进；组长负责主线集成和写字机。

## 获取协作基线

日常协作从 `main` 接续。Windows 发布从 [Windows Git 发布基线](WINDOWS_GIT_BASELINE.md) 接续。20261022 团队基线分支和 0.1.40 记录保留为历史。

```powershell
git clone --recurse-submodules https://github.com/lixiang1haoo-glitch/InkStruct.git
cd InkStruct
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
| 桌面采集内核 | 当前源码随 Windows 基线提供，构建输入哈希见对应发布记录 | 采集内核源码和固定参考资源 |
| 研究作者样本与验证集 | 组长按授权范围单独分发；字集组冻结划分并重新建档 | 不提交 |
| 生成结果、评分和字体 | 每次新目录，记录版本与输入身份 | 不提交 |

```powershell
.venv/Scripts/python.exe -m inkstruct.cli structures build
.venv/Scripts/python.exe -B -m inkstruct.application --workspace workspaces/team
```

旧版独立采集内核源包的清单和安装脚本保留供历史检出使用。安装脚本核验整包与逐文件哈希，并保留已有目录。当前采集内核的来源和许可说明随源码保留。

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
