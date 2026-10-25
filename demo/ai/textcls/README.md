# 文本分类

将英文短句分为 11 个类别。导入后显式调用 `run()`；运行时只读取随包资产，不联网、不写盘。需要提供 `ml.Model` 和 `ulab` 的 mpynn 固件。

```python
from demo.ai import textcls

textcls.run()  # 默认三句已知样本，打印各自 top 3
textcls.run(['fitness exercise health patient', 'mechanical trusses device'])
```

随完整 `demo` 包复制本目录，保留 [模型](text_cls_tflm.tflite)、[词表](vocab.txt) 和 [标签](labels.txt)。默认按包位置寻找资产，也可指定 `directory='/sd/demo/ai/textcls'`。

复用模型时使用上下文管理器，或在 `finally` 中调用 `close()`：

```python
from demo.ai import textcls

with textcls.Classifier(directory='/sd/demo/ai/textcls') as classifier:
    predictions = classifier.classify('career joined attended helped', top_k=3)
    print(predictions)  # [(label, score), ...]，按 score 降序
```

- `run(texts=None, directory=None, backend='reference', arena_size=256*1024)` 返回 `[(text, predictions), ...]`，正常或异常退出均释放模型。单个字符串也可直接作为 `texts`。
- `Classifier(path=None, directory=None, backend='reference', arena_size=256*1024)` 的 `path` 可替换模型路径，词表和标签仍从 `directory` 读取。替换模型必须保持相同张量契约、词表及标签顺序。`close()` 可重复调用，关闭后不能继续分类。
- `classify(text, top_k=3)` 的 `top_k` 范围为 1～11。score 是原始 **logit**，可为负数或大于 1，不能当作置信概率。

分词为转小写、按空白切词、按原始词表行号查表、截断至 50、右补 0，不额外清理标点。词表第一行为空（pad ID 0），第二行为 `[UNK]`（ID 1），未登录词均使用 1。词表共 544 行，覆盖面有限；例如带标点的词可能成为未知词。输入为 float32 ndarray `[1,50]`，模型内部 CAST 为 int32；输出为 float32 `[1,11]`。

默认 `reference` 使用 CPU。可请求 `auto` 或 `vc4`：`auto` 保留固件当前后端开关，`vc4` 通过公开 ML 接口请求 VC4；平台缺少 VC4 控制时可能报错。该模型的最终 FC 输出深度 11 不满足当前 VC4 的 FC16 约束，会走 CPU fallback；不能据此宣称文本分类获得 VC4 加速。

已使用 Windows frozen mpynn/TFLM 的真实 CPU reference 路径验证默认样本：

| 文本 | top1 标签 | 原始 logit |
| --- | --- | ---: |
| `fitness exercise health patient` | `health_medicine` | 0.850558 |
| `mechanical trusses device` | `engineering` | 0.933015 |
| `career joined attended helped` | `career_advice` | 1.140432 |

这些是主机 CPU 功能证据，尚非 Raspberry Pi 板端或 VC4 加速证据。资产来源、SHA-256 与复现命令见 [资产说明](ASSETS.md)。
