# 故障排查

`paper-pdf-figures` 技能的常见问题与修复。

## 依赖检查报缺，但 run.sh 实际能跑

**最常见的问题**：用 PATH 上的 `python3` 跑 `check_deps.py` 报缺依赖（如
`[MISSING] torch`），但 `run.sh` 指向的解释器（如 conda env `test_demo_env`）
里实际全齐。

**根因**：`check_deps.py` 检查的是**运行它的那个 Python** 的环境，不是
`run.sh` 里的 Python。两者可能不同。

**解决**：先读 `run.sh`，用里面的 python 跑 check_deps，或直接跑 `run.sh`
让它自己报缺什么：

```bash
# 看 run.sh 里的解释器
cat ${CLAUDE_SKILL_DIR}/scripts/run.sh
# 用那个解释器跑 check_deps
RUN_PY=$(grep '^exec ' ${CLAUDE_SKILL_DIR}/scripts/run.sh | awk '{print $1}' | sed 's/exec//')
$RUN_PY ${CLAUDE_SKILL_DIR}/scripts/check_deps.py
# 或者直接跑 run.sh，让它自己报
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh paper.pdf --mode auto --out ./out
```

## `auto` 模式："ERROR: --mode auto requires ML backend"

ML 依赖（torch、doclayout-yolo、huggingface_hub）未安装。

```bash
pip install -r ${CLAUDE_SKILL_DIR}/requirements-ml.txt
```

用 **run.sh 的解释器**（不是系统 `python3`）跑 check_deps 验证。无 ML 依赖时
改用 `manual`（配合 `detect` 找 bbox）。

## `auto` 模式：模型权重下载卡住/失败

`auto` 首次运行会从 HuggingFace Hub 下载 DocLayout-YOLO 权重。若
`huggingface.co` 不可达（某些 WSL2/防火墙环境常见）：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

然后重跑 `auto`。权重缓存到 `<skill>/models/huggingface/`（或
`--weights-dir` / `PAPER_PDF_FIGURES_WEIGHTS_DIR`），后续运行很快。

若镜像也不可达，从 `huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench`
手动下载权重文件（文件名 `doclayout_yolo_docstructbench_imgsz1024.pt`），
放到 `--weights-dir/huggingface/...` 缓存路径下。

## 权重已缓存但仍联网失败（SOCKS 代理/网络问题）

若模型权重已下载（缓存目录有 `.pt` 文件），但 `hf_hub_download` 仍尝试
在线验证 etag，因代理配置错误（如 `all_proxy=socks://...`）失败：

```bash
export HF_HUB_OFFLINE=1
```

这会强制跳过在线检查，直接用本地缓存。`model_detect.load()` 已内置此逻辑
（检测到缓存时自动设 `HF_HUB_OFFLINE=1`），但若仍有问题可手动设。

## `auto` 模式：检测到 0 个 figure / table

- 调低 `--min-confidence`（默认 0.3）如 0.2，保留边界区域。
- 加 `--caption-driven-fallback` 救回模型检测到 caption 但漏了 body 的
  table。
- 查看 `candidates/page_NNNN_candidates.png` - 红框是模型检测到的区域。
  若没有 `figure`/`table` 框，模型可能不认这种版式；回退到 `detect`
  （启发式）+ `manual`。
- 看 summary 的 `warnings`：`WARN_NO_FIGURES` / `WARN_NO_TABLES` 在 PDF
  确实没有图表时是正常的。

## `embedded` 模式：提取到 0 张图

PDF 可能是**纯矢量**（图是 PDF 矢量操作画的，不是 image XObject）。常见于
matplotlib/TikZ 导出。`page.get_images()` 返回 0。

- 改用 `auto`（模型检测 figure 区域）或 `manual`（按 bbox 裁剪）。

## `manifest.json` 保存失败（缺 jsonschema）

`jsonschema` 是运行时依赖（`manifest.validate()` 需要），已在
`requirements.txt` 里。若仍报缺：

```bash
# 用 run.sh 的解释器装
RUN_PY=$(grep '^exec ' ${CLAUDE_SKILL_DIR}/scripts/run.sh | awk '{print $1}' | sed 's/exec//')
$RUN_PY -m pip install jsonschema
```

## 裁剪结果里 table 的 caption 缺失

`auto` 在 manifest 里为每个 table 记录 `caption_source`：

- `model` - 模型配对了 `table_caption`（最佳）。
- `text-rescan` - caption 被错分成 `plain text`，已回扫救回。
- `caption-driven` - 从相邻文本块推断出 body（开启
  `--caption-driven-fallback`）。
- `none` - 没找到 caption。裁剪结果仍是 table body，只是没有 caption。

要提高 caption 覆盖率，加 `--caption-driven-fallback`。

## 某个 table 被错分成 `algorithm`

`classify_table_or_algorithm` 启发式检查裁剪文字。规则已收紧（行锚定关键字、
table caption 优先），现在很少见。若发生：

- 看 `algorithms/<id>/<id>.pdf` 的文字 - 若是 table，分类错了。
- 这是启发式局限；裁剪结果仍有效，只是放错了目录。

## `--overwrite` guard："manifest.json already exists"

重跑进已存在的 `<out>/<slug>/manifest.json` 但没加 `--overwrite` 会退出 1。
加 `--overwrite` 替换整个 `<out>/<slug>/` 目录：

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh paper.pdf --mode auto --out ./out --overwrite
```

## `check_deps.py` 退出码

- `0` - 所有必需依赖就绪（所有模式可用）。
- `1` - 缺少必需依赖（部分模式不可用）。报告里 `[MISSING]` 是必需的，
  `[WARN]` 是可选的（pdftocairo/pdfimages/mutool/torch/doclayout-yolo）。

**注意**：check_deps 的结果取决于运行它的 Python 解释器。务必用 `run.sh`
里的 python，不是系统 `python3`。

## 大 PDF 内存不足/慢

- `auto` 每页在 dpi=150 跑模型（检测）。72 页论文 GPU 约 10 秒，CPU 更久。
  用 `--pages` 限定范围，或有 GPU 时 `--device cuda`。
- `render` 高 `--dpi`（如 600）会产生大 PNG；除非要印刷分辨率，用 150-300。
- `--dry-run` 跳过所有写盘（便宜地预览数量）。

## 测试失败

```bash
cd ${CLAUDE_SKILL_DIR} && pytest tests/ -v
```

真实模型 smoke 测试（`test_real_doclayout_detector_smoke`）需要 ML 依赖 +
网络；默认被 deselect（`-k "not real_doclayout"`）。要跑它：

```bash
export HF_ENDPOINT=https://hf-mirror.com
pytest tests/test_model_detect.py::test_real_doclayout_detector_smoke -v
```
