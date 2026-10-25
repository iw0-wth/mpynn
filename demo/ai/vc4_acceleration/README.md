# VC4 加速展示：稠密特征评分器

这是可以直接复制到板子运行的完整演示项目，随附 FP32 TFLite 模型与确定性输入。
它将 **2048 维特征投影为 1024 个评分**，展示同一模型在 CPU 与 VC4 上的输出与耗时。
模型使用全部非零、正负混合权重，是合成计算负载，不代表训练好的业务分类器。

## 板端运行

需要已初始化 VC4、启用 packed16 的当前 mpynn 固件，含原生 ML/ulab、非消费日志快照
和 `vc4_reset_diagnostics()`。已验证基线为 Pi 1B R2 / 512 MiB / ARM700 CORE250。

把整个 `demo` 目录复制到 SD 根目录，确保下列文件均在：

```text
/demo/__init__.py
/demo/ai/vc4_acceleration/__init__.py
/demo/ai/vc4_acceleration/model.tflite
/demo/ai/vc4_acceleration/reference.json
```

在 REPL 执行：

```python
from demo.ai import vc4_acceleration
result = vc4_acceleration.run()
```

重新运行不需要重启。演示会重新构造两个模型，并为本次 VC4 执行重开诊断采样。
可缩短运行次数：

```python
result = vc4_acceleration.run(warmup=2, repeat=10)
print(result['speedup'])
```

若单独把此包放在其他位置，用 `directory='/实际目录'` 指定模型和 JSON 所在目录。
默认直接从本模块目录读取，不依赖电脑路径、开发测试树或当前 REPL 工作目录。

## 展示内容

1. 打印板型/build ID、ARM 时钟、模型规模与本次参数。
2. 在整组运行前用 `machine.vc4(False)` 选择CPU，构造公共 `ml.Model(...)`，保持默认auto后端。
3. 销毁 CPU 模型后，用 `machine.vc4(True)` 选择VC4并重新构造同模型；重复predict期间不逐次切换后端。
4. 分别对原输入和取反输入检查所有 1024 个评分；显示前 8 个评分与最大误差。
5. 打印重复 `predict()` 平均毫秒数和 **CPU / VC4 实测加速比**。
6. 在本次诊断标记之后确认 `dispatch complete` 和
   `in=2048 out=1024 dispatches=1 multitile=1 packed16=1`，明确 GPU 确实执行。

输出形式示意（数值取本次运行结果）：

```text
reference avg_ms: ... max_error: ... changed_input_error: ...
first 8 scores: [...]
vc4 avg_ms: ... max_error: ... changed_input_error: ...
first 8 scores: [...]
GPU evidence: b'... FC matvec timing: ... dispatches=1 ... packed16=1'
CPU / VC4 speedup: ...x
VC4 acceleration observed; both inputs and all 1024 scores match.
```

既往相同稠密模型在 Pi1B 700/250 的板测为 CPU 约64.07 ms、VC4约9.77 ms，约6.56x。
该数字是历史参照，不是当前固件/每次运行的预置结果。若日志证实 QPU 执行但速度比≤1，
程序会如实显示未观察到加速；若只有 CPU fallback 或旧日志，则报错而不宣称加速。

## 计时、正确性和资源

- 默认 warmup=8、repeat=30。按原 `vc4_dense_acceptance.py` 的口径，只在整组开始/结束
  读取一次 `ticks_ms()`，对完整predict循环计时；包含输出分配及循环开销，不含加载模型、
  Prepare/一次性 GPU 权重打包、warmup、golden 检查、打印或日志读取。
- 固定演示整组选择一次 `machine.vc4` 并使用默认auto模型，避免原demo通过显式backend
  在每次predict执行额外的Python导入/后端选择/恢复。通用用户模型接口不变。
  用户同板对照确认旧脚本约6.5x，而原demo约4.7x；此修复统一脚本执行/计时路径，
  实际加速比仍由下一次板端运行决定，不把代码回归当作性能实测。
- 这是单层 FC，每次推理为 2,097,152 MAC；GPU 权重为 8 MiB，模型源和 4 MiB arena
  还要单独计入 RAM。两个模型按顺序释放，避免同时保留两份权重/arena。
- 原输入/取反输入使用随附 binary64 参考值，程序固定使用 `1e-4 + 1e-4*abs(reference)`
  误差界限，并拒绝非有限值；改变 JSON 中的 tolerance 不会放宽实际判定。
- 模型元信息、shape、dtype、输出和日志都检查。文件 SHA-256 记录在
  [ASSETS.md](ASSETS.md)；程序核对 JSON 模型标识，但不假定板端提供 hashlib。
- `finally` 释放模型、回收 GC 并恢复原 `machine.vc4()`。输入/输出对拍失败也会清理。
- 不清除旧日志、不联网、不写文件、不操作 GPIO；结束后 `machine.logs()` 仍可查看记录。
  重采样状态由本次运行显式改变，不会在退出时恢复。
- 若诊断标记被其他大量日志覆盖，程序拒绝用缺失或陈旧证据确认 GPU；可在空闲时重跑。

这是用户演示而非压力测试；不执行超时故障注入、散热/稳定性或并发任务验收。
通用用户模型比较另见 [vc4.py](../vc4.py)，它不要求本演示的固定模型与参考数据。
