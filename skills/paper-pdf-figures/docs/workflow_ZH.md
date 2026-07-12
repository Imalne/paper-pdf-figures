# 使用流程

用 `paper-pdf-figures` 技能从学术 PDF 提取图表的端到端流程。

## 1. 先读 run.sh

`run.sh` 是运行时入口，里面写死了安装时选的 Python 解释器路径（如
`/home/user/anaconda3/envs/myenv/bin/python3`）。**所有依赖检查和执行都必须用
`run.sh` 里的解释器**，不是 PATH 上的 `python3`。

```bash
# 看 run.sh 里的解释器
cat ${CLAUDE_SKILL_DIR}/scripts/run.sh
# 用那个解释器跑 check_deps（不要用 python3！）
# 或者直接跳过检查，跑 run.sh 让它自己报缺什么
```

若要检查依赖，用 `run.sh` 里的 python：

```bash
RUN_PY=$(grep '^exec ' ${CLAUDE_SKILL_DIR}/scripts/run.sh | awk '{print $1}' | sed 's/exec//')
$RUN_PY ${CLAUDE_SKILL_DIR}/scripts/check_deps.py
```

- PyMuPDF / Pillow / PyYAML / numpy / opencv / jsonschema 显示 `[OK]` -> 所有模式可用。
- torch / doclayout-yolo 显示 `[WARN]` -> `auto` 模式需要 ML 后端：
  ```bash
  pip install -r ${CLAUDE_SKILL_DIR}/requirements-ml.txt
  ```
- pdftocairo 显示 `[WARN]` -> SVG 导出不可用（PDF+PNG 仍可用）。
- 退出码 1 表示缺少必需依赖；0 表示全部就绪。

## 2. 选择模式

完整对比见 [extraction-modes_ZH.md](extraction-modes_ZH.md)。快速指南：

- **`auto`**（推荐）：模型检测 figure / table / algorithm 区域，各自与 caption
  合并，裁剪矢量 PDF + PNG。无需 config。
- **`embedded`**：把原始光栅图从 PDF 里抽出来。
- **`manual`**：按 `config.yaml` 里列的 bbox 裁剪指定区域。
- **`detect`**：启发式 dry-run，输出候选 bbox + 预览图（用于给 `manual` 找 bbox）。
- **`render`**：把整页或 bbox 区域光栅化成 PNG + contact sheet。

## 3. 运行

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh PAPER.pdf \
    --out ./out --mode auto --dpi 300 --paper-slug my_paper
```

**如果 `run.sh` 报缺依赖**，装到 `run.sh` 的解释器里（看 `run.sh` 的 `exec` 行），
不是系统 `python3`。

通用 flag：
- `--out DIR`（必需）- 输出目录。
- `--paper-slug NAME` - 子目录名（默认用 PDF 文件名净化后）。
- `--dpi 300` - 渲染分辨率（影响 PNG 尺寸；PDF 保持矢量）。
- `--pages 1,2,5-8` - 限定指定页。
- `--overwrite` - 替换该 slug 已有的输出目录。
- `--dry-run` - 只计算不写文件（无 manifest、无图）。

`auto` 专属 flag：
- `--min-confidence 0.3` - 丢弃低于此置信度的模型区域。
- `--labels figure,table` - 要裁剪的布局类别（caption 自动推断为
  `{primary}_caption`）。
- `--caption-driven-fallback` - 救回模型漏检 body 但检测到 caption 的
  table（默认关闭）。

### `auto` 的网络说明

`auto` 首次运行会从 HuggingFace Hub 下载 DocLayout-YOLO 模型权重。若
`huggingface.co` 不可达，运行前设置镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

权重缓存到 `--weights-dir`（默认 `${CLAUDE_SKILL_DIR}/models/`，或
`PAPER_PDF_FIGURES_WEIGHTS_DIR` 环境变量）。

若模型权重已缓存但网络/代理有问题（如 SOCKS 代理配置错误），设置：

```bash
export HF_HUB_OFFLINE=1
```

这会跳过在线 etag 检查，直接用本地缓存。

## 4. 检查输出

`auto` 的输出目录结构：

```
out/<slug>/
├── figures/          # 裁剪的 figure（每个含矢量 PDF + PNG 预览）
│   └── fig_p0011_01/{fig_p0011_01.pdf, fig_p0011_01.png}
├── tables/           # 裁剪的 table（caption 已合并进 bbox）
├── algorithms/       # 从 table 分离出的算法伪代码块
├── candidates/       # 每页预览 PNG + candidates.json（全部区域）
│   ├── page_0011_candidates.png
│   └── candidates.json
└── manifest.json     # 所有输出的唯一事实源
```

其他模式产出子集：`embedded/`（embedded）、`figures/`（manual）、
`candidates/`（detect）、`pages/` + `regions/` + `summary_contact_sheet.png`
（render）。

## 5. 验证 manifest

```bash
RUN_PY=$(grep '^exec ' ${CLAUDE_SKILL_DIR}/scripts/run.sh | awk '{print $1}' | sed 's/exec//')
$RUN_PY -c "
import sys; sys.path.insert(0, '${CLAUDE_SKILL_DIR}/scripts')
import manifest
m = manifest.Manifest.load('out/<slug>/manifest.json')
print('figures:', len(m.figures), 'tables:', len(m.tables),
      'algorithms:', len(m.algorithms))
print('schema errors:', manifest.validate(m.to_dict()))
"
```

`manifest.json` 记录每个输出项：页码、bbox（PDF point）、sha256、
`extraction_method`、`caption_source`（tables/algorithms 的为
`model` / `text-rescan` / `caption-driven` / `none`）。

## 6. 小贴士

- **先读 run.sh** - 它定义了哪个 Python 有依赖。不要用不同的 `python3` 跑
  依赖检查，否则可能误报缺失（base 环境缺的，run.sh 的环境可能已装）。
- **源 PDF 永不被修改** - 技能只读打开。可用 `sha256sum PAPER.pdf` 前后对比验证。
- **矢量保留**：裁剪的 PDF（figures/tables/algorithms）保留矢量内容 +
  可搜索文字；PNG 仅是光栅预览。
- **caption 恢复**：`auto` 有三层 - 模型 `table_caption` 配对、
  错分 caption 的文本回扫、漏检 body 的 `--caption-driven-fallback`。
- **可复现**：`manifest.json` 的 `run_args` 记录了精确的 CLI flag。
