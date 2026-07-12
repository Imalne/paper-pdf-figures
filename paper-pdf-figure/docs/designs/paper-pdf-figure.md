# Paper PDF Figures Skill — 设计文档

## 1. 目标

实现一个 Claude Code Skill，专门用于从学术论文 PDF 中保存图像资源，技能名：

```text
paper-pdf-figures
```

用户在 Claude Code 中通过如下方式调用：

```bash
/paper-pdf-figures ./paper.pdf --out ./figures --mode auto
```

技能自动完成：

1. 从论文 PDF 中提取内嵌像素图；
2. 从 PDF 页面中按 bbox 裁剪并保存完整 figure 区域；
3. 尽可能保留向量图为 PDF/SVG；
4. 同时导出高分辨率 PNG 预览图；
5. dry-run 检测 figure 候选区域，辅助手动标注；
6. 保存图像元信息：页码、坐标、caption 占位、提取方式、文件哈希；
7. 输出 manifest 文件，方便归档、检索、训练数据构建或人工检查；
8. 验收通过后导出可分发的安装包（`.skill`）。

## 2. 设计原则

### 2.1 同时覆盖两类图像

论文 PDF 中的图像分两类：

- **内嵌像素图**：JPEG、PNG、JPEG2000、TIFF 等，可直接从 PDF object 中抽出。
- **页面完整 figure**：由向量线条、文字、坐标轴、legend、嵌入图片、透明层、字体混合组成，不能按"图片 object"抽取，应按页面区域裁剪，保存为矢量 PDF/SVG 或高分辨率 PNG。

因此 Skill 支持两条路线：

```text
路线 A：PDF 内嵌图片提取   (--mode embedded)
路线 B：页面 figure 区域裁剪 (--mode manual)
路线 C：候选区域 dry-run 检测 (--mode detect)
```

`--mode auto` 在一次运行中编排以上路线。

### 2.2 不修改原 PDF

所有操作只读原始 PDF，输出统一写入用户指定目录。

### 2.3 默认离线运行

不依赖网络，不上传论文，不调用外部 API。`--no-network` 作为显式声明保留，但默认即离线。

### 2.4 先可靠，后自动

MVP 优先实现稳定的命令行工具与手动/半自动裁剪；自动 figure 检测只输出候选（dry-run），不直接裁剪。自动裁剪、caption 匹配、批处理等列为后续独立 spec。

### 2.5 单一事实源

manifest.json 是元信息的唯一事实源，不重复写每张图的 `metadata.json`，避免双份漂移。

## 3. MVP 范围与延期项

### 3.1 纳入 MVP

| 能力 | `--mode` | 依赖 | 输出 |
| --- | --- | --- | --- |
| 内嵌图提取 | `embedded` | PyMuPDF（+ pdfimages 可选对照） | `embedded/*.{jpg,png,...}` |
| 手动 bbox 裁剪 | `manual` | PyMuPDF + PyYAML | `figures/fig_N/{.pdf,.png,.svg}` |
| 候选检测 dry-run | `detect` | numpy + opencv | `candidates/*.png` + `candidates.json` |
| 全页/区域渲染 | `render` | PyMuPDF | `pages/*.png` |
| 一键组合 | `auto` | 以上全部 | 以上全部 + `summary_contact_sheet.png` |
| 打包分发 | 验收后 | `package.sh` | `dist/paper-pdf-figures-<ver>.skill` |

### 3.2 延期为后续独立 spec

以下能力**不在本次实现计划内**，每个对应独立的 spec → plan → 实现周期：

1. caption 提取与匹配（`Figure 1` / `Fig.` / `图 1`）；
2. 批处理 + resume（递归扫描论文目录、断点续跑）；
3. 自动裁剪（MVP 的 `detect` 只 dry-run，不自动裁剪）；
4. 扫描版 PDF 智能分割；
5. 模型检测（DocLayout / YOLO / Detectron2 / LayoutParser）；
6. HTML index 浏览页；
7. GUI bbox 标注小工具；
8. JSONL 训练数据导出；
9. Obsidian / Wolai / GitHub 文档归档接口；
10. 跨路由去重（embedded 与 figures 之间）。

## 4. 技能位置与目录结构

技能根目录：`.claude/skills/paper-pdf-figures/`（匹配本仓库已有的 `wolai-to-github` 布局，可被 Claude Code 自动发现为 `/paper-pdf-figures`）。技能名统一用复数 `paper-pdf-figures`。本设计文档保留在 `paper-pdf-figure/docs/designs/`。

```text
.claude/skills/paper-pdf-figures/
├── SKILL.md
├── README.md
├── VERSION                      # 供 package.sh 与 manifest tool_version 共用
├── scripts/
│   ├── check_deps.py
│   ├── extract_pdf_figures.py   # 主入口, --mode 调度, 薄层
│   ├── extract_embedded.py      # embedded 模式
│   ├── crop_export.py           # manual 模式: 裁剪 + PDF/PNG/SVG
│   ├── figure_detect.py         # detect 模式: dry-run 候选
│   ├── render_pages.py          # render 模式
│   ├── manifest.py              # manifest 数据结构 + schema 校验
│   ├── contact_sheet.py         # summary 缩略图
│   ├── install_deps.sh
│   └── package.sh               # 验收后打包
├── templates/
│   ├── config.example.yaml
│   └── manifest.schema.json
├── docs/
│   ├── workflow.md
│   ├── extraction-modes.md
│   └── troubleshooting.md
└── tests/
    ├── test_manifest.py
    ├── test_extract_embedded.py
    ├── test_crop_export.py
    ├── test_figure_detect.py
    └── fixtures/                # 小样例 PDF
```

主入口 `extract_pdf_figures.py` 只做参数解析与按 mode 调度，各 mode 逻辑分离到独立模块，可独立理解和测试。

## 5. 技术选型与依赖分级

### 5.1 工具与用途

| 工具 | 用途 |
| --- | --- |
| PyMuPDF / `fitz` | 读取 PDF、遍历页面、提取图片、裁剪页面区域、渲染 PNG 预览 |
| Poppler `pdfimages` | 内嵌像素图的高可靠对照提取（可选） |
| Poppler `pdftocairo` | 裁剪后 PDF 转 SVG（可选，缺失则降级） |
| Pillow | 保存与校验 PNG/JPEG 图像 |
| PyYAML | 读取手动标注的裁剪配置 |
| numpy + opencv | `detect` 模式的候选区域检测 |
| MuPDF `mutool` | 备用资源提取（MVP 不使用，延期） |

### 5.2 依赖分级与降级

当前部署环境可能未预装上述工具，因此缺依赖时的行为必须明确：

| 工具 | MVP 必需? | 缺失时行为 |
| --- | --- | --- |
| PyMuPDF (fitz) | ✅ 必需 | 报错退出，提示 `pip install pymupdf` |
| Pillow | ✅ 必需 | 报错退出 |
| PyYAML | ✅ 必需（manual / auto 模式） | manual/auto 报错，其余模式可用 |
| numpy + opencv | ✅ 必需（detect / auto 模式） | detect/auto 报错，其余可用 |
| Poppler `pdftocairo` | ⚠️ 可选 | 跳过 SVG，发 `WARN_SVG_EXPORT_FAILED`，仍出 PDF+PNG |
| Poppler `pdfimages` | ⚠️ 可选 | 仅用 PyMuPDF 提取，不做对照 |
| MuPDF `mutool` | ❌ 延期 | 仅 `WARN_MUTOOL_NOT_FOUND`，MVP 不调用 |

`check_deps.py` 按此表逐项检查，并报告"哪些 mode 因缺依赖不可用"。`install_deps.sh` 处理 `pip install pymupdf pillow pyyaml numpy opencv-python` + `apt install poppler-utils`，并提供无 sudo 的 pip-only 降级路径（此时 SVG 不可用，需明确告知）。

## 6. CLI 设计

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py PDF_PATH [options]
```

### 6.1 基础参数

```text
--mode embedded|manual|detect|render|auto
--out OUTPUT_DIR
--config CONFIG_YAML              # manual / auto 模式使用
--pages 1,2,5-8
--dpi 300|600
--formats pdf,png,svg
--paper-slug NAME
--overwrite
--dry-run
```

### 6.2 detect 专用参数

```text
--min-area-ratio 0.03
--max-area-ratio 0.85
--merge-distance 20
--exclude-margins 30
--two-column auto|true|false
```

### 6.3 通用参数

```text
--no-network                      # 默认即离线, 保留作显式声明
--verbose
--log-file run.log
```

### 6.4 模式语义

- `embedded`：提取内嵌像素图。
- `manual`：按 `--config` 中的 page + bbox 裁剪完整 figure，导出 PDF/PNG/SVG。
- `detect`：dry-run，只输出候选 bbox + 预览图 + `candidates.json`，不裁剪。
- `render`：把整页或 `--pages` 指定区域渲染为 PNG。
- `auto`：依次跑 embedded + detect(dry-run) +（若给 `--config`）manual，结束时生成 contact sheet。

> 说明：原设计的 `crop` 模式与 `manual` 合并；caption 相关参数（`--extract-captions` 等）随 caption 能力延期。

### 6.5 路由 A/B 关系

`auto` 模式下，一张既是内嵌图又落在 manual 裁剪区内的图，会在 `embedded/` 和 `figures/` 各出一份——用途不同（原始资源 vs 组合图），manifest 各自记录。MVP 不做跨路由去重（embedded 内部按 xref + sha256 去重）。

## 7. 功能详述

### 7.1 功能 1：提取内嵌像素图（`embedded`）

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py \
  input.pdf --out output_dir --mode embedded
```

输出：

```text
output_dir/
└── paper_slug/
    ├── embedded/
    │   ├── p0003_xref0012.jpeg
    │   ├── p0007_xref0048.png
    │   └── p0010_xref0061.jp2
    └── manifest.json
```

实现：

1. 优先用 PyMuPDF 的 `page.get_images()` + `doc.extract_image(xref)` 提取；
2. 若系统存在 `pdfimages`，可额外调用 `pdfimages -all` 做对照（可选）；
3. 同一 xref 图片去重；
4. 保存每张图的页码、xref、宽高、色彩空间、扩展名、文件大小、sha256。

### 7.2 功能 2：裁剪完整 figure（`manual`）

保存论文中完整的图，包括向量曲线、坐标轴、legend、子图编号、内嵌图片、图中文字。

输出格式：`figure_NNN.pdf` + `figure_NNN.png`，可选 `figure_NNN.svg`（依赖 `pdftocairo`）。

实现路线：

1. 用 PyMuPDF 按 bbox 从原 PDF 裁剪出小 PDF；
2. 用 PyMuPDF 或 `pdftocairo -png -r 300/600` 渲染 PNG 预览；
3. 若 `pdftocairo` 可用，调用 `pdftocairo -svg` 导出 SVG；否则跳过 SVG 并发 warning；
4. 所有 bbox 用 PDF point 坐标记录，方便复现。

### 7.3 功能 3：手动 bbox 配置

第一版必须支持手动配置。示例 `config.yaml`：

```yaml
pdf: paper.pdf
output_dir: figures
paper_slug: my_paper_2026
figures:
  - id: fig_001
    page: 3
    bbox: [72, 110, 540, 410]
    caption: "Figure 1: Overview of the proposed framework."
    export:
      - pdf
      - png
      - svg

  - id: fig_002
    page: 5
    bbox: [60, 95, 550, 690]
    caption: "Figure 2: Quantitative and qualitative comparison."
    export:
      - pdf
      - png
```

调用：

```bash
/paper-pdf-figures ./paper.pdf --config ./config.yaml
```

> `caption` 字段在 MVP 中只原样存储，不做自动提取或匹配（随 caption 能力延期）。

### 7.4 功能 4：候选区域 dry-run 检测（`detect`）

MVP 只做轻量启发式检测，**只输出候选，不自动裁剪**：

1. 每页低 DPI 渲染；
2. 二值化 + 形态学闭运算；
3. 连通域检测；
4. 合并邻近区域；
5. 按面积、宽高比、位置过滤（排除页眉、页脚、小公式）；
6. 转换为 PDF point bbox；
7. 输出带框预览图 + `candidates.json`；
8. 支持 `--dry-run`（detect 模式本身就是 dry-run，该参数对其他模式生效）。

输出：

```text
candidates/
├── page_003_candidates.png
├── page_004_candidates.png
└── candidates.json
```

`candidates.json` 中的 bbox 可直接复制进 `config.yaml` 继续裁剪。caption 结合、双栏列判断的进阶匹配随 caption 能力延期。

### 7.5 功能 5：manifest 导出

每次运行生成 `manifest.json`（见 §8）。

### 7.6 功能 6：contact sheet

`auto` 模式结束时生成 `summary_contact_sheet.png`：每个 figure 的缩略图 + 页码 + id + caption 前几个词，作为人工验收入口。contact sheet 随 Phase 5 的 `contact_sheet.py` 引入，仅 `auto` 模式产出。

## 8. Manifest schema

`templates/manifest.schema.json` 正式定义 schema。manifest.json 是元信息唯一事实源，不再写每张图的 `metadata.json`。

示例结构：

```json
{
  "source_pdf": "paper.pdf",
  "paper_slug": "my_paper_2026",
  "created_at": "2026-07-04T00:00:00",
  "tool_version": "0.1.0",
  "run_args": {"mode": "auto", "dpi": 600},
  "figures": [
    {
      "id": "fig_001",
      "page": 3,
      "bbox_pdf_points": [72, 110, 540, 410],
      "type": "page-crop-mixed",
      "caption": "Figure 1: Overview of the proposed framework.",
      "files": {
        "pdf": "figures/fig_001/fig_001.pdf",
        "png": "figures/fig_001/fig_001.png",
        "svg": "figures/fig_001/fig_001.svg"
      },
      "sha256": {"pdf": "...", "png": "...", "svg": "..."},
      "extraction_method": "manual-bbox",
      "dpi": 600
    }
  ],
  "embedded_images": [
    {
      "id": "embedded_p0003_xref0012",
      "page": 3,
      "xref": 12,
      "format": "jpeg",
      "width": 1200,
      "height": 800,
      "file": "embedded/p0003_xref0012.jpeg",
      "sha256": "..."
    }
  ],
  "candidates": [
    {"page": 3, "bbox_pdf_points": [70, 108, 542, 412], "score": 0.82}
  ],
  "warnings": [
    {"code": "WARN_SVG_EXPORT_FAILED", "page": 5, "detail": "pdftocairo not found"}
  ]
}
```

`tool_version` 取自 `VERSION` 文件。运行后自动校验 manifest 符合 schema（见 §13）。

## 9. 输出文件命名规范

稳定、可排序、可追踪。

### 9.1 论文目录

```text
{paper_slug}/
```

`paper_slug` 默认从 PDF 文件名生成：

```text
2301.00001v2_some_paper.pdf → 2301_00001v2_some_paper
```

### 9.2 内嵌图像

```text
embedded/p{page:04d}_xref{xref:06d}.{ext}
# 例: embedded/p0003_xref000012.jpeg
```

### 9.3 裁剪图像

```text
figures/fig_{index:03d}/fig_{index:03d}.pdf
figures/fig_{index:03d}/fig_{index:03d}.svg
figures/fig_{index:03d}/fig_{index:03d}.png
```

### 9.4 候选区域

```text
candidates/page_{page:04d}_candidates.png
candidates/candidates.json
```

### 9.5 contact sheet

```text
summary_contact_sheet.png
```

### 9.6 渲染整页（`render` 模式）

```text
pages/p{page:04d}.png
# 例: pages/p0003.png
```

## 10. 打包与分发

验收通过后运行 `scripts/package.sh`：

- 产出 `dist/paper-pdf-figures-<version>.skill`（**zip** 格式，匹配本仓库 `wolai-to-github.skill` 的既有约定）；
- 包内顶层目录为 `paper-pdf-figures/`，包含 `SKILL.md`、`README.md`、`VERSION`、`scripts/`、`templates/`、`docs/`；
- version 取自 `VERSION`，与 manifest `tool_version` 一致；
- `package.sh` 流程：
  1. 运行 `check_deps.py` 确认必需依赖齐全；
  2. 清理 `__pycache__`、`*.pyc`、测试产物；
  3. 打包为 zip；
  4. 写 `dist/MANIFEST.txt`（包内文件清单 + 每个文件的 sha256）。
- 安装方式：解压到 `~/.claude/skills/` 或项目 `.claude/skills/`，运行 `install_deps.sh` 装系统依赖。

## 11. 分阶段实现路线

每个 phase 可独立测试与验收。

### Phase 0：Skill 骨架

交付物：`SKILL.md`、`VERSION`、`check_deps.py`、`install_deps.sh`、`manifest.py` 骨架 + `manifest.schema.json`。

验收：

1. `/paper-pdf-figures` 能被 Claude Code 识别；
2. `check_deps.py` 能正确报告每个依赖状态与"哪些 mode 不可用"；
3. `manifest.py` 能加载/校验空 manifest。

### Phase 1：内嵌像素图提取（`embedded`）

交付物：`extract_embedded.py`、`extract_pdf_figures.py` 调度骨架。

功能：PyMuPDF 提取 → xref 去重 → 保存原始扩展名 → 写 manifest → 输出 summary。

验收：

1. 对普通论文 PDF 能提取内嵌 JPEG/PNG；
2. 重复图片不重复保存；
3. manifest 记录 page、xref、width、height、format、sha256；
4. 原 PDF 未被修改。

### Phase 2：手动 bbox 裁剪 PDF + PNG（`manual`）

交付物：`crop_export.py`、`templates/config.example.yaml`。

功能：读 YAML → 按 page + bbox 裁剪 → 导出 PDF → 渲染 PNG → 写 manifest。

验收：

1. 能正确裁剪向量图，裁剪后 PDF 可放大查看；
2. PNG 预览清晰；
3. manifest 记录 bbox 与导出文件。

### Phase 3：SVG 导出

交付物：`crop_export.py` 增加 SVG 路径。

功能：接入 `pdftocairo -svg`；缺失时降级跳过并发 `WARN_SVG_EXPORT_FAILED`。

验收：

1. 有 `pdftocairo` 时导出可用的 SVG；
2. 无 `pdftocairo` 时优雅跳过，其余格式正常，manifest 记录 warning。

### Phase 4：候选 dry-run 检测（`detect`）

交付物：`figure_detect.py`。

功能：每页生成候选 bbox → `candidates.json` → 带框预览图 → 支持 `--dry-run`。

验收：

1. 对两栏论文能找到主要图区域；
2. 对公式、页眉、页脚误检较少；
3. 候选 bbox 可直接复制进 `config.yaml`。

### Phase 5：contact sheet + `auto` 编排

交付物：`contact_sheet.py`、`extract_pdf_figures.py` 的 `auto` 模式。

功能：`auto` 串联 embedded + detect +（若给 config）manual；生成 `summary_contact_sheet.png`。

验收：

1. `auto` 一次运行产出全部三类输出；
2. contact sheet 缩略图可读，含页码、id、caption 前几个词。

### Phase 6：打包（验收后）

交付物：`scripts/package.sh`。

功能：产出 `dist/paper-pdf-figures-<ver>.skill` + `dist/MANIFEST.txt`。

验收：

1. 包可在另一处解压安装并运行 `check_deps.py` 通过；
2. `MANIFEST.txt` 列出全部文件与 sha256。

## 12. 测试计划

### 12.1 测试 fixture

仓库当前无任何样例 PDF。MVP 准备 3 个极小 fixture，放 `tests/fixtures/`：

1. 单栏向量图论文片段；
2. 双栏论文片段；
3. 含内嵌 raster 图的片段。

其余 PDF 类型（扫描版、旋转页、透明图层、长 supplementary、表格/算法块等）列为"后续迭代用真实论文验证"。

### 12.2 单元测试

重点测试：

1. manifest schema 校验；
2. bbox 坐标转换（PDF point ↔ 像素）；
3. 文件命名规则；
4. sha256 计算；
5. xref 去重；
6. `config.yaml` 读取；
7. `--pages` 参数解析（`1,2,5-8`）；
8. 输出目录创建与 `--overwrite` 行为；
9. `--dry-run` 行为；
10. 降级行为（mock 缺失 `pdftocairo`，验证 SVG 跳过 + warning）。

### 12.3 人工检查

contact sheet 即验收入口：每个 figure 的缩略图、页码、id、caption 前几个词，快速扫一遍是否裁剪正确。

## 13. 质量控制与 warning

### 13.1 自动检查项

每次运行后检查：

1. 输出文件是否存在、大小是否为 0；
2. PNG 能否正常打开；
3. PDF 是否至少 1 页；
4. SVG 是否成功生成（若请求）；
5. bbox 是否越界；
6. 是否存在重复 sha256（embedded 内部）；
7. manifest 是否符合 schema。

### 13.2 标准 warning

```text
WARN_NO_EMBEDDED_IMAGES
WARN_NO_FIGURE_CANDIDATES
WARN_BBOX_OUT_OF_PAGE
WARN_SVG_EXPORT_FAILED
WARN_DUPLICATE_IMAGE
WARN_CAPTION_NOT_FOUND        # MVP 不自动匹配, caption 字段为空时发此 warning
WARN_ENCRYPTED_PDF
WARN_SCANNED_PDF
WARN_MUTOOL_NOT_FOUND
```

## 14. 关键难点与处理策略

### 14.1 向量图不是图片 object

很多 figure 是 PDF 绘图指令和文字，不是单独 image object。策略：支持页面区域裁剪并保存为 PDF/SVG，不依赖单纯图片提取。

### 14.2 自动检测容易误检

公式、表格、算法框、页眉页脚可能被误认为 figure。策略：MVP 的 detect 只输出候选，不直接裁剪，用户确认后手动配置。

### 14.3 SVG 导出不总是稳定

某些 PDF 的字体、透明层、clip path 在 SVG 中可能异常。策略：始终保留裁剪后的 PDF 作为主矢量结果，SVG 为可选格式，PNG 为视觉预览；`pdftocairo` 缺失或导出失败时降级跳过。

### 14.4 扫描版 PDF

扫描版每页通常是一张大图，无独立 figure object。策略：走页面渲染 + CV 检测路线；MVP 只提供候选框，不承诺完美自动分割。智能分割延期。

### 14.5 双栏 caption 匹配

caption 可能在图下方、上方或跨栏。策略：MVP 不做匹配，caption 字段由用户在 `config.yaml` 填写；自动匹配随 caption 能力延期。

## 15. 安全策略与 `allowed-tools`

### 15.1 安全规则

1. 不访问网络；
2. 不上传 PDF；
3. 不执行用户未请求的删除操作；
4. 默认不覆盖已有输出；
5. 所有输出路径限制在用户指定目录下；
6. 对 PDF 文件名做 sanitize；
7. 对外部命令参数使用列表形式调用，避免 shell injection；
8. README 明确说明依赖与权限。

### 15.2 `allowed-tools`

`SKILL.md` frontmatter 保留最小三条，便于技能运行时免频繁授权提示，同时审计面可控：

```yaml
allowed-tools:
  - Bash(python3 *)
  - Read
  - Write
```

> 不预批准 `pdfimages` / `pdftocairo` / `mutool` 等外部二进制——这些通过 `python3` 脚本以 subprocess 列表形式调用，仍走正常授权。若后续发现提示过多，可再按需追加。

## 16. SKILL.md 入口设计

`SKILL.md` 保持简短，详细说明放 `docs/`。

````markdown
---
name: paper-pdf-figures
description: Extract and save figures from academic PDF papers, including embedded raster images and vector-preserving page crops. Use when the user wants to extract, crop, archive, or batch-save images/figures from research papers.
allowed-tools:
  - Bash(python3 *)
  - Read
  - Write
---

# Paper PDF Figures

Use this skill when the user wants to extract or save figures from academic PDF files.

## Main workflow

1. Identify the input PDF path and output directory.
2. Check dependencies:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/check_deps.py
   ```
3. Choose an extraction mode:
   * `embedded`: extract original embedded raster images.
   * `manual`: crop figure regions from user-provided bbox config.
   * `detect`: dry-run candidate figure detection (no crop).
   * `render`: render full pages or selected regions to PNG.
   * `auto`: run embedded + detect + (optional) manual, plus contact sheet.
4. Run:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/extract_pdf_figures.py "$ARGUMENTS"
   ```
5. Report:
   * number of embedded images extracted;
   * number of figure crops exported;
   * output directory;
   * manifest path;
   * warnings or failed pages.

## Important rules

* Never modify the original PDF.
* Do not upload PDFs or images to external services.
* Prefer vector-preserving PDF/SVG export for page-level figures.
* Use high-DPI PNG only as preview or raster fallback.
* `detect` only outputs candidates — do not auto-crop; ask the user to confirm bbox.

## Additional references

* Detailed workflow: docs/workflow.md
* Extraction modes: docs/extraction-modes.md
* Troubleshooting: docs/troubleshooting.md
````

## 17. 依赖安装

### 17.1 Python 依赖

```bash
python3 -m pip install --user pymupdf pillow pyyaml numpy opencv-python
```

### 17.2 系统依赖

Ubuntu/Debian：

```bash
sudo apt-get install poppler-utils
```

无 sudo 环境：

1. 优先使用已有系统模块；
2. 或在用户目录编译/安装 Poppler；
3. 或只启用 PyMuPDF 路线（此时 SVG 不可用，降级跳过）。

`install_deps.sh` 自动探测 sudo 可用性，走对应路径，并明确提示 SVG 是否可用。

## 18. 典型使用方式

### 18.1 只提取内嵌像素图

```bash
/paper-pdf-figures ./paper.pdf --out ./figures --mode embedded
```

### 18.2 自动生成候选区域（dry-run）

```bash
/paper-pdf-figures ./paper.pdf --out ./figures --mode detect
```

### 18.3 根据配置裁剪 figure

```bash
/paper-pdf-figures ./paper.pdf --config ./figure_config.yaml
```

### 18.4 输出高分辨率 PNG

```bash
/paper-pdf-figures ./paper.pdf --config ./figure_config.yaml --formats pdf,png --dpi 600
```

### 18.5 一键 auto + SVG

```bash
/paper-pdf-figures ./paper.pdf --config ./figure_config.yaml --mode auto --formats pdf,svg,png
```

### 18.6 验收后打包

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/package.sh
# → dist/paper-pdf-figures-<ver>.skill
```

## 19. 后续增强方向（延期项）

见 §3.2。每项为独立 spec，按需排期：

1. 跨路由图像去重（sha256、感知哈希、尺寸、位置）；
2. 自动 caption 识别与匹配；
3. 图表/照片/流程图/可视化结果分类；
4. LaTeX 源码辅助定位 figure；
5. arXiv 批量处理 + resume；
6. HTML index 浏览页；
7. GUI bbox 标注小工具；
8. JSONL 训练数据导出；
9. Obsidian / Wolai / GitHub 文档归档接口；
10. 论文 supplement 联合处理。

## 20. 最终交付物清单

```text
.claude/skills/paper-pdf-figures/
├── SKILL.md
├── README.md
├── VERSION
├── scripts/
│   ├── check_deps.py
│   ├── extract_pdf_figures.py
│   ├── extract_embedded.py
│   ├── crop_export.py
│   ├── figure_detect.py
│   ├── render_pages.py
│   ├── manifest.py
│   ├── contact_sheet.py
│   ├── install_deps.sh
│   └── package.sh
├── templates/
│   ├── config.example.yaml
│   └── manifest.schema.json
├── docs/
│   ├── workflow.md
│   ├── extraction-modes.md
│   └── troubleshooting.md
└── tests/
    ├── test_manifest.py
    ├── test_extract_embedded.py
    ├── test_crop_export.py
    ├── test_figure_detect.py
    └── fixtures/
```

验收后另产出：

```text
dist/paper-pdf-figures-<ver>.skill
dist/MANIFEST.txt
```

## 21. 建议开发顺序

```text
Step 1:  创建技能目录、SKILL.md、VERSION
Step 2:  check_deps.py + install_deps.sh
Step 3:  manifest.py + manifest.schema.json
Step 4:  extract_pdf_figures.py 调度骨架
Step 5:  extract_embedded.py(Phase 1)
Step 6:  crop_export.py PDF + PNG(Phase 2)
Step 7:  crop_export.py SVG + 降级(Phase 3)
Step 8:  figure_detect.py dry-run(Phase 4)
Step 9:  contact_sheet.py + auto 编排(Phase 5)
Step 10: 加测试 + fixture
Step 11: 真实论文 PDF 上迭代参数
Step 12: 人工验收
Step 13: package.sh 打包(Phase 6)
```
