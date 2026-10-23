# InkStruct 团队协作

本仓库维护生成主线、桌面应用、字集研究与评测及公共接口。Android 在独立私有仓库 [InkStruct-Android](https://github.com/lixiang1haoo-glitch/InkStruct-Android) 开发。先阅读 [环境与资源准备](docs/COLLABORATION.md)，取得固定子模块、结构库和必要的采集内核依赖包。

## 分支与审阅

从协作基线创建短期功能分支，建议 feature、fix、research 或 docs 前缀；Codex 分支用 codex 前缀。通过 PR 合并，不直接覆盖 main，不强推其他成员分支。普通修改由另一位成员检查，生成核心、公共协议和应用版本由组长复核。CODEOWNERS 标明归属，强制审阅依赖实际分支保护设置和账号功能。

PR 写清具体问题、改变后的行为、验证命令、资源或协议影响，以及未完成的设备检查。跨仓库修改互相引用 Issue／PR，记录接口来源提交。

## 环境与验证

使用 Python 3.12 至 3.13，安装 `pip install -e ".[desktop,dev]"`。桌面与确定性研究无需 CUDA；旧 requirements 和训练脚本不作为新成员默认入口。安装脚本不得清空已有环境。

```powershell
.venv/Scripts/python.exe scripts/check_repository_hygiene.py
.venv/Scripts/python.exe -B -m pytest tests/test_character_sets.py tests/test_generation_targets.py tests/test_collection_receipt.py tests/test_recommend.py tests/test_v61_starter_collection.py tests/test_v62_semantics.py -p no:cacheprovider
```

先运行相关测试，再做上述基础检查。基础 CI 不代表完整桌面、真机输入、生成质量或写字机验收；涉及这些路径的修改须另附证据。

## 数据和发布

原始样本、作者档案、评分、生成结果、迁移快照、发布包、虚拟环境和凭据留在受控本地目录。不要强制添加被忽略的数据。Make Me a Hanzi 保留固定子模块与上游许可证；外部采集内核按有哈希的源文件包提供，不重新声明其许可。

APP_VERSION 是应用版本唯一来源。新构建由组长统一递增版本、同步说明及文件名，历史交付不覆盖；Python 库和字体格式独立管理。
