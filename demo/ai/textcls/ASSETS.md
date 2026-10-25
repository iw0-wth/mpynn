# 资产来源与核验

本目录三个资产来自用户授权读取的项目原始目录 [ml_text_cls](../../../../ml_text_cls/)。复制前已确认三个目标均不存在；采用二进制逐字节复制，没有重训、转换模型或改写文本换行。下表 SHA-256 同时适用于源文件和本目录副本。

| 资产 | 字节数 | SHA-256 |
| --- | ---: | --- |
| [text_cls_tflm.tflite](text_cls_tflm.tflite) | 643304 | `aecd63afecd8c318691254a7c4e6e591f44c817e4254379e29db1046b15b38e5` |
| [vocab.txt](vocab.txt) | 4336 | `18846140150bf300a36f5491853d9ffd76978cd8c9516dbd94e4949fceae342f` |
| [labels.txt](labels.txt) | 133 | `183e69f1e5ab0af051a1f70192d8053cc5d018f8e6820b0b5c76eca5f9986870` |

使用项目已有的 TFLite schema 解析器核验：schema version 3，单子图、单输入 float32 `[1,50]`、单输出 float32 `[1,11]`；输入连接 CAST，转换为 int32；图中无 Softmax。词表共 544 行，空首行 pad=0，第二行 `[UNK]`=1，标签 11 项。分数按 logit 原值返回。

真实推理使用项目现有 Windows frozen 运行时，命令从项目根目录执行：

```powershell
& D:/openmv_aicore/mpynn/build/windows-frozen-ml/mpynn-ml.exe -c "import sys; sys.path[:]=['.frozen','D:/openmv_aicore/mpynn']; from demo.ai import textcls; textcls.run()"
```

主机 CPU reference 实测 top 3（顺序为标签与原始 logit）：

| 文本 | top 3 |
| --- | --- |
| `fitness exercise health patient` | `health_medicine 0.850558`, `internships_jobs 0.819261`, `study 0.512130` |
| `mechanical trusses device` | `engineering 0.933015`, `internships_jobs 0.668542`, `sports 0.520113` |
| `career joined attended helped` | `career_advice 1.140432`, `internships_jobs 1.115092`, `technology 0.532582` |

运行真实 frozen `ml`、`ulab` 与 TFLM，不使用 fake 模型作为推理证据。这里记录的是 Windows 主机 CPU 功能结果，未验证 Raspberry Pi 板端时延或 VC4 加速。最终 FC 的 11 个输出不符合当前 VC4 FC16 约束；`auto`/`vc4` 请求不代表该层成功派发 QPU。

外部 [host 测试](../../../../tests/raspberrypi/test_demo_textcls.py) 单独覆盖分词编号、未知词、标签契约、logit 原值及异常释放；控制流用的 fake 模型与真实 frozen 子进程测试分开。测试不是部署依赖，复制 demo 不需要复制 tests。运行：

```powershell
& D:/anaconda3/python.exe -B -m pytest tests/raspberrypi/test_demo_textcls.py -q -p no:cacheprovider
```
