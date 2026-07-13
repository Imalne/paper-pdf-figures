---
name: paper-pdf-figures
description: Extract and save figures from academic PDF papers, including embedded raster images and vector-preserving page crops. Use when the user wants to extract, crop, archive, or batch-save images/figures from research papers.
allowed-tools:
  - Bash(python3 *)
  - Read
  - Write
---

# Paper PDF Figures（中文版）

当用户想从学术 PDF 文件中提取或保存图表时，使用此技能。

## 主流程

1. 确定输入 PDF 路径和输出目录。
2. **首次使用**：检查 `${CLAUDE_SKILL_DIR}/scripts/run.sh` 是否存在。
   * **如果 `run.sh` 存在**：读它 -- 它包含安装了所有依赖的 Python 解释器路径，是唯一事实来源。不要用别的 `python3` 跑 `check_deps.py`。
   * **如果 `run.sh` 不存在**（如通过 `/plugin install` 安装但没跑安装器）：先跑安装器：

     ```bash
     bash ${CLAUDE_SKILL_DIR}/scripts/install.sh
     ```

     这会装 Python 依赖（基础 + 可选 ML）、生成 `run.sh`（含正确解释器路径）、设置 HF 镜像。跑完后 `run.sh` 就存在了，后续都用它。
     非交互模式：`bash ${CLAUDE_SKILL_DIR}/scripts/install.sh --yes --no-ml`
3. 选择模式：
   * `auto` - **推荐**。基于模型：检测 figure / table / algorithm 区域，各自与 caption 合并，自动裁剪矢量 PDF + PNG（无需 config）。需要 ML 依赖。
   * `embedded` - 提取原始内嵌光栅图（JPEG/PNG/JP2/TIFF）。无需模型。
   * `manual` - 按 `--config CONFIG.yaml` 中的 bbox 裁剪 figure 区域。保留矢量。
   * `detect` - 启发式候选检测，仅 dry-run（输出候选 bbox + 预览图，不裁剪）。无需模型；用于为 `manual` 找 bbox。
   * `render` - 把整页（`--pages`）或 bbox 区域（`--config`）渲染成 PNG + contact sheet。
4. 运行（把用户的请求解析成 CLI flag 后执行）：
   ```bash
   bash ${CLAUDE_SKILL_DIR}/scripts/run.sh <PDF路径> --mode <模式> --out <输出目录> [FLAG]
   ```
   示例：`bash ${CLAUDE_SKILL_DIR}/scripts/run.sh paper.pdf --mode auto --out ./figures --dpi 300`
   **如果 `run.sh` 报缺依赖，装到 `run.sh` 的解释器里**（看 `run.sh` 的 `exec` 行），不是系统 `python3`。
   通用 flag：`--out DIR`、`--paper-slug NAME`、`--dpi 300`、`--pages 1,2,5-8`、`--overwrite`、`--dry-run`。
   `auto` 专属 flag：`--min-confidence 0.3`、`--labels figure,table`、`--caption-driven-fallback`（救回模型漏检的 table）。
   若 `huggingface.co` 不可达，运行 `auto` 前设置 `HF_ENDPOINT=https://hf-mirror.com`。
   若模型权重已缓存但网络/代理有问题，设置 `HF_HUB_OFFLINE=1`。
5. 从打印的 summary 报告：
   * 各类数量（`embedded_images` / `figures` / `tables` / `algorithms` / `candidates` / `rendered`）；
   * 输出目录和 `manifest.json` 路径；
   * 警告（如 `WARN_NO_FIGURES`、`WARN_NO_TABLES`）。

## 重要规则

* **先读 `run.sh` 再做任何事** -- 它定义了哪个 Python 有依赖。所有依赖检查和执行都必须用那个解释器，不是系统 `python3`。
* 永不修改原始 PDF（只读打开；验收时用 sha256 验证）。
* 不向外部服务上传 PDF 或图片；除首次运行下载模型权重外全程离线。
* 提取 figure 优先用 `auto`；无 ML 依赖时回退到 `manual`（配合 `detect` 找 bbox）。
* 裁剪的 PDF（figures/tables/algorithms）保留矢量内容；PNG 仅作光栅预览。
* `detect` 按设计是 dry-run - 它从不裁剪。要裁剪，把它的候选 bbox 放进 `manual` 的 config，或直接用 `auto`。

## 参考文档

* 详细流程：[docs/workflow_ZH.md](docs/workflow_ZH.md)
* 提取模式：[docs/extraction-modes_ZH.md](docs/extraction-modes_ZH.md)
* 故障排查：[docs/troubleshooting_ZH.md](docs/troubleshooting_ZH.md)
