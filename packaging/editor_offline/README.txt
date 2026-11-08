InkStruct 混排编辑器离线安装材料

这是按平台整理的 Python 依赖包，不包含 Python 本身，也不是免安装应用。
先安装 Python 3.13：macOS 包需要 Apple Silicon 和 macOS 14 或更新版本；
Windows 包需要 x64 Python。请使用对应平台的包，两个包不能混装。

1. 将整个目录复制到可写位置，保留 wheels、requirements.lock 和 manifest.json。
2. macOS：在此目录执行 python3.13 install.py。
   Windows：在此目录执行 py -3.13 install.py。
   安装仅使用本地 wheels，不查询网络索引，不修改系统或其他项目的环境。
3. 安装成功后双击对应的“启动编辑器”脚本。
   若系统阻止未签名脚本，可用终端运行：
   macOS：runtime/bin/python -I -m inkstruct.editor.app
   Windows：runtime\Scripts\python.exe -I -m inkstruct.editor.app

仅验证材料：Python 3.13 执行 install.py --verify-only。
功能验证：使用 runtime 中的 Python 执行 smoke.py --output 新的验证目录。
无显示服务器的自动验证需设置 QT_QPA_PLATFORM=offscreen。
验证覆盖编辑器构建、数字/公式/表格、项目保存重开、严格 SVG 及 PDF 子进程。
离屏通过不代表输入法、屏幕缩放、文件对话框或写字机试写已通过。

若安装中途失败，runtime 会保留供检查；请将原离线包复制到新目录后重试，
安装程序不会自动清除或复用已有 runtime。完整移动已安装目录可能破坏虚拟环境，
换位置时请从原材料重新安装。新版本也应在新的目录安装。

样本和个人项目不包含在此包中。内置数字可验证基础排版；汉字及其他手写符号
需导入自己的资源或含内嵌资源的 .inkdoc。原始资源和项目请另行备份。
文件哈希用于发现材料损坏，不是数字签名；请从可信来源接收整包。
第三方依赖许可证保留在各 wheel 中。本包未签名、未公证。
Windows 的实际安装和原生交互仍须在 Windows 设备上验证，见项目交付说明。
