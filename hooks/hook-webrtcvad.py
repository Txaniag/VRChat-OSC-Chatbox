# webrtcvad 的 hooks-contrib 元数据钩子在本环境崩溃：
# pip 发行版名是 webrtcvad-wheels，钩子却查 webrtcvad 的元数据。
# 本实现覆盖它：webrtcvad 是纯 C 扩展模块，收集动态库即可，无额外数据文件。
from PyInstaller.utils.hooks import collect_dynamic_libs

datas = collect_dynamic_libs('webrtcvad')
