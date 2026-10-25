# Pi 1B Rev2 实板验收入口

用户演示已迁移到独立目录，操作说明见 [demo README](../../demo/README.md)，
测试清单见 [demo TEST_CHECKLIST](../../demo/TEST_CHECKLIST.md)，
进度见 [demo PROGRESS](../../demo/PROGRESS.md)。不再以开发test脚本作为用户demo。

本轮新开发镜像（已编译/静态检查，尚未实板验证该更新）：

- 路径：`build/RPI1B/bin/kernel.img`（相对mpynn根目录）
- 大小：1,387,832 字节
- SHA-256：`13619c5249789001b1183d7fa69d732ffc7dff7721835d38f26837bbc6525060`
- build_id：`f84d191ede603230c166de1db19878c8d0027bf4960e526b45c7cee7e31770c4`
- 更新：原生 uml/TFLM reference、ulab 4D、PNG/BMP/PNM VFS 图片、WAV/PCM 文件音频；保留标准 mpy-lib requests 与 TLS。

用户已确认旧镜像（build_id f452e679...927b6e）在Pi1B Rev2的SD读写正常；
请按各版本记录结果，不再把旧“等待SD结果”历史条目视作当前状态。
本次用户实板启动日志已记录：`Jan 1 00:00:03.55 mpynn: Pi1B RAM: Circle low free 438 MiB, MicroPython GC 406 MiB, reserve 32 MiB`。这表示当前启动配置下约 438 MiB 进入 Circle 低地址可分配区，其中 406 MiB 给 MicroPython GC，32 MiB 保留给 Circle 后续网络/USB/SD 分配；不是 512 MiB 全部可直接给 VM。

更换开发内核前备份SD，第一阶段启动包不变。网络配置切换前关闭应用socket。
软件RTC冷启动2000年；默认requests HTTPS不要求校时，完整CERT_REQUIRED验证
仍须提供CA并设置正确UTC。网络demo不在import时联网，SD写入需显式write=True。
