# 开发测试与用户演示的分工

本目录保留开发主机回归、旧板端测试和历史验收资料。
**用户演示、操作说明和实板检查项请统一使用独立 demo 目录：**

- [操作说明](../../demo/README.md)
- [测试清单](../../demo/TEST_CHECKLIST.md)
- [当前进度与实板证据](../../demo/PROGRESS.md)
- [当前镜像信息](../../ports/raspberrypi/BOARD_ACCEPTANCE.md)

用户已确认Pi1B Rev2的SD读写正常，不再引用历史“无SD实板证据”作为当前结论。
默认CERT_NONE和显式CERT_REQUIRED分别验证，不把加密请求等同完整身份验证。
开发测试不得作为Pi网络/推理硬件通过的替代证据。
