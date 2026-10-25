# mpynn — MicroPython Neural Network

**mpynn（MicroPython Neural Network）是为 AI 推理与计算特化的 MicroPython 固件项目。**
它以 OpenMV 的工程组织和 ML API 设计为起点，保留 `ml.Model` 作为公共入口，使用标准
MicroPython 内核、TFLM 推理引擎和可替换的硬件后端，聚焦神经网络、张量计算及设备应用。

mpynn 同时保留**以自身为基础继续移植 OpenMV 功能的能力**：保留相关源码、工程组织和
可扩展的板级/模块边界，便于后续按目标硬件接入图像处理、采集、显示或其他 OpenMV
能力。AI 特化体现在默认固件的取舍；这些能力需要实际移植和验证后启用，并非当前所有
端口已经具备完整 OpenMV 兼容性。

当前主要目标是 **Raspberry Pi 1 Model B / BCM2835 / VideoCore IV**：由 Circle
提供裸机平台服务，MicroPython 提供交互、脚本和文件系统，TFLM 执行模型，VC4 加速
符合条件的 FP32 全连接层。Windows 端口用于真实 MicroPython/原生 ML 栈的 host 验证。
其他板型可沿板级入口扩展，现有旧板型目录不代表已经完成 mpynn 适配。

**未来端口将重点面向带 NPU 的 MCU，以及算力与内存足够的 SoC。** 新端口围绕可用的
推理引擎、NPU/GPU/CPU 后端、张量内存与数据通路适配，尽量复用公共 Python API 和模型
生命周期；RPI1B/VC4 是当前落地目标，不限定项目长期只支持树莓派或某一种加速器。

## 来源与版本基线

本项目的 OpenMV 工程基线来自工作区的 `D:/openmv_aicore/openmv-master`，对应：

- 上游仓库：[openmv/openmv](https://github.com/openmv/openmv)。
- 上游提交：[`222310c96500a7f6d63a37ae90e02db8dbbe35f7`](https://github.com/openmv/openmv/commit/222310c96500a7f6d63a37ae90e02db8dbbe35f7)。
- 定位依据：原始源码 ZIP 的 Git 提交标识，并与该提交的 Git tree/blob 逐文件核对；
  本地 `openmv-master` 目录的 4,488 个上游文件也全部匹配，无缺失或内容差异。
  不能用归档名 `master` 或 `SDK_VERSION=1.7.3` 代替准确版本。

这是 **OpenMV 工程的来源版本**，不是当前所有依赖的版本。mpynn 已将 MicroPython
切换到标准内核 v1.29.0，并按 [.gitmodules](.gitmodules) 独立固定其他依赖。
原 OpenMV 的品牌、相机产品介绍及其完整功能列表不作为 mpynn 的功能承诺。

## 项目定位与执行关系

mpynn 面向由用户提供模型和数据的推理应用：张量、文件图像、文件音频、网络与板级 I/O
可以组合使用，摄像头和 IDE 预览不是 ML 运行的前提。

```text
Python application
    ml.Model / preprocessing / callbacks
        native uml.Model + ulab
            TFLM MicroInterpreter + standard operator resolver
                CPU kernels
                TFLM-VC4 FP32 FullyConnected -> vc4-runtime
                                                platform C callbacks
                                                    Circle adapter on RPI1B
```

各层职责：

| 层 | 当前实现与职责 |
| --- | --- |
| Python API | 保留 `ml.Model`，处理标签、预处理、回调及 backend 选择 |
| 原生绑定 | `uml.Model` 加载模型、管理 arena、转换 tensor，输出独立 ulab 数组 |
| 推理引擎 | 一份 TFLM archive，标准算子注册，按支持条件选择 CPU 或 VC4 |
| VC4 runtime | 常驻权重、packed16、multi-tile、QPU 提交、缓存、超时及诊断状态 |
| 平台适配 | Circle 管理启动、内存/IRQ、SD、USB 网络及协作调度；通过 C 接口接入 runtime |

[vc4-runtime](lib/vc4-runtime/README.md) 与其中提供的 TFLM-VC4 接入文件为 mpynn 编写，
也可供其他 BCM VC4 项目使用。runtime 本体不依赖 Circle 或 MicroPython；其他裸机框架
可以提供同一平台接口。当前实现与实测基线是 BCM2835，其他 SoC 需要核对硬件协议并验证。

## 相比 OpenMV：裁剪、保留与替换

这里的“裁剪”主要指 **当前 RPI1B 固件的源码选择与功能配置**。仓库中保留的历史端口、
厂商 SDK、驱动和示例不一定被删除，但不会因此自动进入 Pi 固件。保留这些资产也是为了
继续以 mpynn 为基础移植 OpenMV；后续端口可按需求恢复并适配相关模块，无需把相机/IDE
链路设为 AI 核心运行的强制依赖。

| 对象 | RPI1B 当前处理 |
| --- | --- |
| OpenMV 相机 sensor/CSI、传感器探测及采集 | 不编入；不提供伪造摄像头数据的 stub |
| 摄像头 framebuffer、快照/流媒体、IDE 图像预览 | 不编入 |
| OpenMV IDE transport、调试/RPC 协议与相机控制链 | 不编入；使用标准 MicroPython raw/friendly REPL |
| LCD/display 与相机板专用时钟/GPIO/USB 启动约定 | 不作为 Pi 端口依赖 |
| STM32、Alif、i.MX RT 等旧板型与 HAL | 保留源码供参考，当前 Pi 构建不选择 |
| CMSIS-NN/DSP、Ethos-U、ST/Alif 专用加速链 | 当前 Pi ML 路径不使用 |
| 完整 OpenMV 图像分析库 | 不作为原生 image 模块整体迁入；替换为独立文件图像子集 |
| MicroPython | 使用标准 v1.29.0 内核，平台差异放在端口与受控适配层 |
| OpenMV ML Python 包及 `ml.Model` 设计 | 保留并接入新的原生绑定/TFLM 后端，解除对摄像头的依赖 |
| ulab | 保留原生 C 张量计算，配置支持四维 ndarray |
| TFLM | 保留标准模型/schema/解释器和算子 API，特化 FP32 FC |
| requests / ntptime 等 Python 库 | 通过 manifest 使用标准 micropython-lib 包 |
| AprilTag、其他未启用子模块 | 保留原 OpenMV 指针，不代表在 Pi 上启用 |

详细比较见 [OPENMV_CUTS.md](ports/raspberrypi/OPENMV_CUTS.md)。该文档和阶段性状态文件
包含历史快照；当前功能选择以端口源码、配置和本 README 为准。

## 当前保留的运行能力

- **语言与交互**：标准 MicroPython VM/GC、编译器、raw/friendly REPL、Ctrl-C、软复位、
  scheduler、JSON、select、浮点与整数计算，以及配置启用的 f-string/t-string。
- **存储**：通过 Circle SDHOST/EMMC 接入 FAT/VFS，启动卡挂载为 `/`，读取 `boot.py` 和
  `main.py`；不将同一启动卡再次暴露为独立 `machine.SDCard` 挂载设备。
- **网络**：USB LAN9512 Ethernet、IPv4/DHCP/静态配置、UDP/TCP、DNS A、超时/poll、
  端点查询与部分 socket options；通过标准 `tls`/`ssl` 接入 mbedTLS、标准 requests。
- **板级接口**：Pin、延迟到 VM 的 Pin IRQ、硬件 I2C/SPI、SoftI2C/SoftSPI、Timer、WDT、
  软件 RTC/time 和内存/板信息诊断。UART0 用作 REPL，通用 UART/PWM 类尚未启用。
- **ML**：冻结 `ml` 包、原生 `uml.Model`、ulab；支持模型文件或 bytes、ndarray/可调用输入、
  postprocess callback、量化输入转换及输出反量化。当前 VC4 只加速符合条件的 FP32 FC，
  量化算子与其他算子走相应 CPU 实现。
- **文件媒体**：原生 `image` 支持 PNG、未压缩 BMP、PNM 的解码、像素、裁剪/缩放/灰度、
  有限绘制与 ndarray 转换；原生 `audio` 支持 WAV PCM16/raw PCM 文件和 VM 回调。
  JPEG、完整 OpenMV image API、摄像头、实时麦克风采集尚未接入。

这些是当前代码接入范围，不等于每个 API 都已有完整实板覆盖。IPv6、完整 POSIX/CPython
socket 兼容、线程、native emitter 等不在当前已启用范围。

## RPI1B 与 VC4 特化

### 板级与运行时

- 首个板型为 Pi 1 Model B R2 / 512 MiB，BCM2835、ARM1176JZF-S、AArch32、VFPv2
  hard-float；基准配置固定 **ARM 700 MHz / CORE 250 MHz**。
- [RPI1B 板级入口](ports/raspberrypi/boards/RPI1B/README.md) 选择板配置，再进入公共端口
  构建；后续板型各自提供选择文件和入口，而不是在公共 Makefile 中不断添加硬编码分支。
- Circle 拥有启动、MMU、IRQ、平台堆与调度；GC 从已测量可用的低内存区分配，保留
  32 MiB 给 Circle 网络/USB/SD 工作，要求至少 16 MiB GC 空间。
- ARM 端口的 NLR/GC 寄存器保存覆盖 VFP callee-saved 寄存器；Python 回调放在 VM
  上下文，不在硬件 IRQ 内执行。

### 推理与权重布局

- TFLM 保持标准 `Register_FULLY_CONNECTED()`；`CO_PROCESSOR=vc4` 替换同名 FC 源码。
  不双链接两份完整 TFLM archive，也不改变模型 schema。
- Prepare 分配并上传常驻 GPU 权重，原始模型仍为 row-major，供 CPU fallback 使用。
- **multi-tile** 使每 QPU 循环处理多个 16 行 tile，1024x2048 / 12 QPU 从 6 次提交降为
  1 次，workspace 从 103056 降为 13296 bytes，uniform 从 98496 降为 384 bytes。
  单独这一改动的性能改善有限，主要瓶颈仍是权重访存。
- **packed16** 将 GPU 权重改为 `[tile][k][lane]`，使同一 k 的 16 个 lane 读取连续
  64 bytes，减少 TMU/cache 等待；不改变权重字节数，不修改源模型。
- CPU float fallback 在 ARM VFP hard-float 下使用四累加器；bias 与 fused activation
  在 ARM 处理。Prepare 失败可回退，提交后的 timeout/I/O 错误不静默重跑 CPU。
- timeout 时保留可能仍被 QPU 使用的资源，后续确认完成后再回收 deferred-free。

当前生产配置为：

```text
VC4_ENABLE=1
VC4_MULTI_TILE=1
VC4_PACKED_WEIGHTS=1
VC4_PROFILE_COUNTERS=1
VC4_POLL_STRIDE=256
VC4_WAIT_SLEEP_US=10
```

完整算法、ABI、演进、计数器及 TFLM 生命周期说明见 [VC4 runtime README](lib/vc4-runtime/README.md)。

### 日志与构建一致性

```python
import machine
machine.logs()                       # 默认保留快照，可重复查看
machine.logs(clear=True)             # 显式消费当前日志
machine.vc4_reset_diagnostics()      # 下一次推理前重开诊断采样
```

日志环分配 16 KiB，最多保留 16383 bytes，写满覆盖最旧内容。VC4 每个诊断会话仅采样
前 8 次 dispatch；读取日志不会触发新采样。日志快照和诊断重采样是不同机制。

Windows 构建会统一 MSYS/native GCC 的 `BUILD` 路径表达，显式依赖生成的 QSTR 头，
并在生成镜像时校验最终 ELF 的字符串池、冻结引用范围和内存布局。该检查是通用一致性
校验，不硬编码某个 Python 包的预期导入名。build ID 用于辨识源码/配置，镜像 SHA-256
用于辨识二进制；二者不互相代替，也不代表实板验收。

## 公共 ML API

```python
import ml
from ulab import numpy as np

model = ml.Model('/model.tflite', backend='auto', arena_size=2 * 1024 * 1024)
try:
    # 以下形状仅为示例，实际应匹配 model.input_shape / input_dtype。
    x = np.array([0.0], dtype=np.float).reshape((1, 1))
    outputs = model.predict([x])
    print(outputs)
finally:
    model.deinit()
```

`backend` 可为 `auto`、`reference`、`vc4`。`auto` 保留当前平台开关，`reference` 使用
CPU 路径，`vc4` 允许 VC4 尝试；指定 `vc4` 不保证每个算子都上 GPU。应结合实际
eligibility、完成日志及 CPU/VC4 对照验证。模型形状、数据类型和 arena 大小由应用确定。

## 依赖与固定提交

[.gitmodules](.gitmodules) 保留 OpenMV 的子模块路径组织；下面的提交是主仓库 gitlink，
不是跟随远程分支的浮动版本。

| 路径 | 仓库 | 固定提交 |
| --- | --- | --- |
| `lib/micropython` | [micropython](https://gitee.com/wth_iw0/micropython) | `0fd6c573ea815774668bbb16b8e197c8822368b2` |
| `lib/tinyusb` | [tinyusb](https://gitee.com/wth_iw0/tinyusb) | `aa0fc2e08f1c2dd6f026a431e8989357fbb4c5bf` |
| `modules/ulab` | [micropython-ulab](https://gitee.com/wth_iw0/micropython-ulab) | `d161443327173bcf94c2616cb5de37e290af71ca` |
| `lib/tflm/libtflm` | [libtflm-mpynn](https://gitee.com/wth_iw0/libtflm-mpynn) | `9008e63d0acb5a3c739a46af85636e837c6835b2` |
| `lib/vc4-runtime` | [vc4-runtime](https://gitee.com/wth_iw0/vc4-runtime) | `92faccf96be7edb65ddfe2138192e0ac2d6f793f` |
| `lib/circle` | [circle](https://gitee.com/wth_iw0/circle) | `7a81e1b480fe7d19fc1fc695b89bff0a0848f44b` |
| `lib/apriltag` | [OpenMV apriltag](https://github.com/openmv/apriltag) | `636b9ba14ba8485c9fc09590cd4ef53f11427966` |
| `tools/alif` | [alif-security-toolkit](https://github.com/micropython/alif-security-toolkit) | `63698efe8567eed115fe620d5e5de75f460310d7` |
| `scripts/libraries/microdot` | [microdot](https://github.com/miguelgrinberg/microdot) | `b241dfce270883e5018f0b8ec8f5821ea4fe156e` |

最后三项沿用 OpenMV，当前 RPI1B 不依赖它们。tinyusb 指针也保留在工程中；当前
RPI1B 的 USB host/LAN9512 由 Circle 实现，并非自动使用 TinyUSB。
MicroPython 内部为开发复制的嵌套库不在本轮统一重置；本地状态说明见
[LOCAL_REPOSITORY.md](docs/LOCAL_REPOSITORY.md)。

## 构建 RPI1B

从 mpynn 根目录初始化所需的一级子模块：

```sh
git submodule update --init lib/micropython lib/tinyusb modules/ulab \
  lib/tflm/libtflm lib/vc4-runtime lib/circle
```

需要 GNU Make、Python 3、匹配的 ARM bare-metal 工具链，以及 manifest 所需的
micropython-lib/mbedTLS 等嵌套依赖。现有开发工作区已经准备它们；新克隆时需按标准
MicroPython 的依赖设置补齐，不要把一级子模块初始化等同于所有嵌套依赖已就绪。

ARM TFLM-VC4 实现与构建仓库：[wth_iw0/tflite-micro-vc4](https://gitee.com/wth_iw0/tflite-micro-vc4)。
它与 `lib/tflm/libtflm` 的头文件/库资产仓库、`lib/vc4-runtime` 的硬件运行库职责不同。

**当前 Pi Makefile 默认链接工作区同级 `../tflite-micro` 中单独构建的 ARM TFLM-VC4
archive。** 新工作区可从上述仓库获取源码并将本地目录命名为 `tflite-micro`，与 mpynn
并列。`lib/tflm/libtflm` 中的 CPU reference archive 不能被当成 VC4-specialized archive。
首次构建前应准备兼容版本的源码/overlay，使用 `TARGET=rpi1b CO_PROCESSOR=vc4` 构建，
或通过 `TFLM_LIB` 指定现成兼容 ARM TFLM-VC4 archive 的绝对路径。该外部源码仓库当前
不属于主仓库的一级子模块；构建时需另行记录其版本，不将远程默认分支当作固定版本。
细节见 [TFLM-VC4 集成](lib/vc4-runtime/integrations/tflm/README.md)。

本工作区 Windows/MSYS2 示例：

```sh
export PATH=/e/arm-none-eabi/bin:/usr/bin:$PATH
cd /d/openmv_aicore/mpynn
make -C ports/raspberrypi/boards/RPI1B -j8 PYTHON=D:/anaconda3/python.exe

# 顶层兼容入口，同样经过板级选择：
make TARGET=RPI1B -j8 PYTHON=D:/anaconda3/python.exe
```

可追加 `TFLM_LIB=<ARM-VC4-archive绝对路径>`。POSIX 环境使用匹配的 `arm-none-eabi-`
工具链与本机 Python 3。默认输出在 `build/RPI1B/bin/`，包括镜像、ELF、map 与布局报告；
对象、Circle 构建 stage 和工具产物也在 `build/` 中，不修改既有上游源码。

将生成的镜像与板级启动配置、匹配的 Raspberry Pi boot firmware 配合使用。构建过程
不格式化或写入物理 SD 卡。UART0 为 115200 8N1。详细步骤与新板型接入见
[RPI1B 构建说明](ports/raspberrypi/boards/RPI1B/README.md)。

## 测试与演示布局

开发测试位于工作区同级 `../tests/`，不再作为 mpynn 源仓库的内部目录。RPI 端口中的
smoke、验收、benchmark 和测试模型生成器已归入 `../tests/raspberrypi/`；端口仅保留
manifest、构建、镜像/QSTR 校验及其必要工具。编译期配置约束保留在端口内，因此普通
固件构建不要求外部测试目录存在。

用户可直接运行的操作示例集中在 [demo](demo/README.md)，按 `system/`（系统）、
`network/`（网络）、`ai/`（模型应用）分类，不导入测试树或开发夹具。
[textcls](demo/ai/textcls/README.md) 配齐英文文本分类模型、词表和11类标签，可通过
`from demo.ai import textcls; textcls.run()` 运行或输入自己的文本；其原始评分不是概率。
测试脚本负责断言、golden 对拍和故障路径；demo 负责明确传参、展示使用方式及释放资源。
其中 [VC4 加速评分器](demo/ai/vc4_acceleration/README.md) 随附模型和输入，可通过
`from demo.ai import vc4_acceleration; vc4_acceleration.run()` 直接展示同模型 CPU/VC4
评分、平均耗时、加速比和本次 GPU dispatch 证据，无需自行生成测试夹具。
独立 `vc4-runtime` 子模块自身的测试由该项目管理，不在本次主项目测试迁移范围内。

## 验证现状与范围

- Pi1B 已有基础 REPL、SD 读写、基础 TCP echo 及 VC4 FP32 FC 的实板记录。
- 已报告的 1024x2048 稠密 FC 测试覆盖原输入/取反输入、所有输出、布局/计数器和模型
  释放后重建。700/250 下 CPU 约 64.07 ms、packed16 约 9.77 ms，约 **6.56x**；
  GPU 最大误差约 `1.33514408e-05`，通过固定绝对/相对容差。
- 上述性能属于当时对应 build ID 的固件。独立 runtime 提取、日志默认快照等后续修改
  已通过 host/ARM 静态验证，不能自动继承旧二进制的实板认证。
- host 测试覆盖真实 MicroPython 原生 ML、TFLM float/int8、文件媒体、张量所有权、平台
  callbacks、packed/uniform 布局、错误回退和资源回收；它们不模拟 QPU 算术。
- 多数外设、电气行为、完整网络/TLS 场景、真实 timeout/deferred-free 故障注入与热稳定性
  仍需逐项实板验收。单个模型的加速比也不能推广到所有网络。

历史状态文档可能包含旧默认值、旧哈希和阶段性未完成项，应结合源码及记录的 build ID
阅读。不要从旧 OpenMV README 或保留的目录推断支持范围。

## 目录与进一步阅读

| 目录/文档 | 用途 |
| --- | --- |
| [ports/raspberrypi](ports/raspberrypi/README.md) | 当前裸机端口、Circle 适配、网络/机器接口 |
| [ports/raspberrypi/boards/RPI1B](ports/raspberrypi/boards/RPI1B/README.md) | 1B 板级入口和配置选择 |
| [boards/RPI1B](boards/RPI1B/board_config.mk) | 当前板架构、功能配置和启动时钟的唯一来源 |
| [ports/windows](ports/windows/README.md) | Windows 原生 ML 验证端口 |
| [lib/vc4-runtime](lib/vc4-runtime/README.md) | 自有独立 runtime 与 TFLM-VC4 技术文档 |
| [scripts/libraries/ml](scripts/libraries/ml/ml-core/ml/model.py) | 公共 ML Python facade 与工具 |
| [modules/image_file](modules/image_file/image_file.mk) / [modules/audio](modules/audio/audio_file.c) | 独立文件图像/音频原生模块 |
| [demo](demo/README.md) | 用户演示与板端操作入口；历史镜像信息需核对 |
| [../tests](../tests/README.md)（与 mpynn 同级） | 独立开发测试树，含 host/ARM/板级验收与测试模型生成器 |
| [docs/LOCAL_REPOSITORY.md](docs/LOCAL_REPOSITORY.md) | 本地基线、submodule 指针与开发副本说明 |

## 许可证与端口边界

**RPI/Circle 端口按 Circle 的 GPLv3 许可要求分发。** 当前
[raspberrypi 端口](ports/raspberrypi/README.md) 依赖并链接 Circle，包含其平台适配代码的
树莓派固件应遵守 GPLv3；各源文件原有的版权声明与许可通知仍须保留。

该端口的许可边界不意味着整个 mpynn 仓库统一改为 GPLv3：

| 范围 | 许可说明 |
| --- | --- |
| RPI/Circle 端口及链接 Circle 的固件 | 遵守 Circle 的 GPLv3 要求，包括留在端口内的 VC4 Circle 平台适配器 |
| 独立 `vc4-runtime` | 保持其自身许可；独立 runtime 核心采用 MIT，不因被 RPI 端口使用而统一改为 GPLv3 |
| `tflite-micro-vc4` / TFLM 算子接入 | 保持 TFLM 相关源码的 Apache-2.0 等原有许可，不依赖 Circle |
| 其他端口 | 按各自源码及实际链接依赖的许可分发，不继承 RPI/Circle 端口的 GPLv3 |
| OpenMV 保留代码和其他第三方组件 | 保留各自的版权、许可及使用条件，不因本项目名称或端口划分而重新许可 |

独立 VC4 组件可以在其他项目中通过非 Circle 平台后端使用；其独立许可不免除将它们
链接进 Circle 固件时对该固件适用的 GPLv3 要求。具体文件以所属组件的许可证和源码
声明为准，本节说明组件与端口边界，不覆盖或移除原有许可条件。
