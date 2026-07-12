# 提取模式

技能有五个模式，用 `--mode` 选择。所有模式只读打开源 PDF，输出写到
`--out/<paper-slug>/`。

## 对比

| 模式 | 作用 | 需要模型？ | 输出 | 典型用途 |
| --- | --- | --- | --- | --- |
| `auto` | 模型检测 figure / table / algorithm 区域，合并 caption，裁剪矢量 PDF + PNG | 是（ML 依赖）| `figures/`、`tables/`、`algorithms/`、`candidates/`、`manifest.json` | 默认图表提取 |
| `embedded` | 抽取原始内嵌光栅图（image XObject）| 否 | `embedded/`、`manifest.json` | 拿出 PDF 里的照片/光栅图 |
| `manual` | 按 `config.yaml` 里的 bbox 裁剪 figure 区域 | 否 | `figures/`、`manifest.json` | 已知 bbox 时的精确控制 |
| `detect` | 启发式候选检测，dry-run | 否 | `candidates/`、`manifest.json` | 找候选 bbox 喂给 `manual` |
| `render` | 整页或 bbox 区域光栅化成 PNG + contact sheet | 否 | `pages/` 或 `regions/`、`summary_contact_sheet.png`、`manifest.json` | 页面缩略图/区域截图 |

## `auto`（推荐）

基于模型。用 DocLayout-YOLO 检测布局区域，然后：

1. 每页检测区域（`figure`、`figure_caption`、`table`、`table_caption`、
   `plain text`、`title`、`isolate_formula` 等）。
2. **配对 + 合并**：每个 `figure` 与最近的 `figure_caption`（按垂直距离）
   配对；每个 `table` 与最近的 `table_caption` 配对。caption 的 bbox 并入
   主区域 bbox，使裁剪结果包含 caption 文字。
3. **caption 恢复**（三层）：
   - `model` - 模型检测到 `*_caption` 区域并配对成功。
   - `text-rescan` - 无 caption 配对，但找到一个以 `Table N:` 开头的
     `plain text`/`title` 区域，合并进来。
   - `caption-driven`（开启 `--caption-driven-fallback`）- 模型检测到
     caption 但漏了 table body；从相邻文本块推断 body。
4. **algorithm 分离**：对每个裁剪出的 table 读文字分类；若像伪代码
   （`Algorithm N`、`Input:`+`Output:`、`Require:`，或行首
   `for`/`while`/`return`），移到 `algorithms/`，`type="page-crop-algorithm"`，
   id 前缀 `alg_`。
5. 用 `crop_figures` 裁剪（保留矢量的 PDF + PNG）。

每个 table/algorithm 的 `caption_source` 记录 caption 由哪层产生。

### `auto` 的 flag

- `--min-confidence 0.3` - 丢弃低于此置信度的区域（调低如 0.2 可救回
  边界 table）。
- `--labels figure,table` - 要裁剪的主类别。caption 自动推断为
  `{primary}_caption`。直接传 caption 类别（`figure_caption`）会被忽略。
- `--caption-driven-fallback` - 开启 caption-driven 救回（默认关闭）。
- `--device auto|cpu|cuda` - 推理设备。
- `--weights-dir PATH` - 模型权重缓存（默认 `<skill>/models/`）。

## `embedded`

用 PyMuPDF 的 `page.get_images()` + `doc.extract_image()` 提取 image XObject。

- 按 xref 去重（同一图在多页出现 -> 一个文件，记录在首次出现的页）。
- `sha256` 是提取后（可能重新编码）字节的哈希，不是原始内嵌流的。
- 纯矢量 PDF（如 matplotlib 导出的 Form XObject）会提取到 0 张图 -
  这种用 `auto` 或 `manual`。

```bash
bash .../run.sh paper.pdf --mode embedded --out ./out
```

## `manual`

按 `config.yaml` 里列的 bbox 裁剪成矢量 PDF + PNG。裁剪用
`page.show_pdf_page(clip=bbox)`，把区域作为 Form XObject 嵌入 -
**矢量内容和文字都保留**（可放大、可搜索）。

`config.yaml` 格式（见 `templates/config.example.yaml`）：

```yaml
pdf: paper.pdf
figures:
  - id: fig_001
    page: 3
    bbox: [72, 110, 540, 410]   # [x0, y0, x1, y1]，PDF point
    caption: "Figure 1: Overview."
    export: [pdf, png]          # 可选；默认两者
```

```bash
bash .../run.sh paper.pdf --mode manual --config config.yaml --out ./out --dpi 300
```

## `detect`

启发式 dry-run。每页：低 DPI 渲染 -> Otsu 二值化 -> 形态学闭运算 ->
连通域 -> 按面积比/宽高比/页边过滤 -> 合并邻近。输出候选 bbox + 预览图，
**从不裁剪**。

用于给 `manual` 找 bbox：读 `candidates.json`，挑一个 bbox，复制进
`config.yaml`。

```bash
bash .../run.sh paper.pdf --mode detect --out ./out --min-area-ratio 0.03
```

flag：`--min-area-ratio`、`--max-area-ratio`、`--merge-distance`、
`--exclude-margins`、`--two-column`（接受但尚未接入算法；存入 `run_args`
作前向兼容）。

## `render`

把页面光栅化成 PNG（无矢量输出）。两种行为：

- **无 `--config`**：整页渲染 -> `pages/p{page:04d}.png`（用 `--pages` 过滤）。
- **有 `--config`**：渲染 config 里每个 figure 的 bbox 区域 ->
  `regions/{id}.png`（与 `manual` 同 config 格式，但输出光栅）。

总是生成 `summary_contact_sheet.png`（4 列缩略图网格）。

```bash
# 整页
bash .../run.sh paper.pdf --mode render --out ./out --pages 1,11 --dpi 150
# 区域
bash .../run.sh paper.pdf --mode render --config config.yaml --out ./out
```

## Manifest

每个模式都写 `manifest.json`（唯一事实源）。数组：

- `figures[]` - 裁剪的 figure（`manual`/`auto`）。
- `tables[]` - 裁剪的 table（`auto`）。
- `algorithms[]` - 分离出的算法块（`auto`）。
- `embedded_images[]` - 提取的光栅图（`embedded`）。
- `candidates[]` - 带 `label`/`confidence` 的检测区域（`auto`/`detect`）。
- `rendered[]` - 渲染的页面/区域（`render`）。
- `warnings[]` - `WARN_NO_FIGURES`、`WARN_NO_TABLES`、
  `WARN_NO_EMBEDDED_IMAGES`、`WARN_NO_RENDERED`、`WARN_SVG_EXPORT_FAILED`
  等。

`run_args` 记录精确的 CLI flag，便于复现。
