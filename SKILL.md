---
name: medical-record-structuring
description: "批量处理 Word 文档(.docx，含病历/病例/医学报告)为结构化信息，支持单个文档或整个文件夹的多个文档批量处理：图转文(MinerU OCR)、敏感词识别与脱敏(医院名/人名掩码)、按字段结构化提取并导出结果表格。分两阶段：先图转文+脱敏输出产物，用户确认后按用户提供的表头字段 excel 提取。适用：病历/病例/医学文档/文档批量结构化、脱敏、识别医院名/人名、提取患者信息、图转文 OCR、按表头/字段批量提取、生成结构化结果表。"
version: 1.1.0
author: company
---

# 病例信息结构化 Skill

把上传的病历 docx 分两阶段处理：先「图转文 + 脱敏」，用户确认后再「结构化提取 + 输出表格」。外部能力由 MCP 提供，确定性处理由脚本完成。

## 能力总览

| 阶段 | 步骤 | 能力 | 载体 |
|---|---|---|---|
| 一 | 图转文 | docx → Markdown(每图一个一级标题) | `references/mcp_client/mineru_call.py`（直连 `mineru-mcp` 8010，容器内路径 `/ws/...` 自动转换） |
| 一 | 脱敏 | 识别医院名/人名 + 掩码 | `references/mcp_client/llm_sensitive.py`（直连 `llm-mcp` 8011）+ `desensitize/scripts/mask.py` |
| 二 | 结构化提取 | 按字段提取 → 结果表 | WorkBuddy 模型（右下角选择）+ `read_fields.py` |
| 二 | 规则检查 | 脱敏完整性/格式/空值校验 | `rule-check/` 子技能 |

## Workflow（两阶段，按需推进）

**阶段一（图转文 + 脱敏）—— 用户上传 docx 后执行：**
1. `docx-ocr`：docx → Markdown（用 `references/mcp_client/mineru_call.py`，长超时直连）。
2. `desensitize`：识别敏感词 + 掩码（用 `references/mcp_client/llm_sensitive.py`）。
3. 输出三个产物：① 图转文 Markdown ② 敏感词清单 ③ 脱敏全文。
4. **停下询问用户**：是否需要继续做结构化提取？（不自动进入阶段二）

**阶段二（结构化提取）—— 仅当用户确认后执行：**
5. 用户上传「提取字段 excel」（单行表头，每格一个字段名，如 性别/年龄/诊断）。
6. `extract`：按字段提取。
7. `rule-check`：规则检查。
8. 输出结果表格：每行一个 docx，第一列 docx 标题，后面每列对应 excel 表头字段。

## 铁律（必须遵守）

1. **每次任务用独立干净的输出目录**：形如 `output/<文档名>/`，开始前确认该目录不存在或为空；**禁止读取/复用历史任务的产物**（旧的 markdown、xlsx、sensitive_words.txt、result.json 等）。
2. **字段一律以用户本次提供的 excel 为准**：用户没提供「提取字段 excel」时，不得擅自沿用历史字段或旧模板；必须在阶段一结束后停下询问。
3. **长任务（图转文/批次识别）一律走固定直连库 `references/mcp_client/`**：会话内 MCP 客户端约 2 分钟超时，整份病历 OCR 需 5~8 分钟，故不得用会话内工具做长任务。改用 `references/mcp_client/mineru_call.py` / `llm_sensitive.py`（直连本机 8010/8011 streamableHttp，长超时默认 1800s）。**禁止为单个任务临时手写 HTTP 客户端脚本**——如有新需求，先把能力补进 `references/mcp_client/` 库再复用。
   - 仅当任务确实很短（<1MB 纯文本、单次识别）且会话内工具已加载、能稳定在 2 分钟内返回时，才可用会话内 MCP 工具。
4. **流式输出和对话记录不要含有敏感词**：禁止敏感词出现在workbuddy的流式输出和对话记录中。

## Activation Contract（路由）

路由详见 `references/activation-map.yaml`。稳定 skill id：`docx-ocr` / `desensitize` / `extract` / `rule-check`。

- 子技能缺失时：优先读本地相对路径 `references/<skill-id>/SKILL.md`，不要联网抓取。
- MCP 工具在当前会话不可用时：不阻塞，提示用户确认本机 Docker 容器 `mineru-mcp`(8010) / `llm-mcp`(8011) 是否在跑，并检查 `mcp.json`。

## Reference index

- [activation-map.yaml](references/activation-map.yaml)
- [docx-ocr/SKILL.md](references/docx-ocr/SKILL.md)
- [desensitize/SKILL.md](references/desensitize/SKILL.md)
- [extract/SKILL.md](references/extract/SKILL.md)
- [rule-check/SKILL.md](references/rule-check/SKILL.md)
- [mcp_client/（固定直连库：mineru_call.py / llm_sensitive.py / mcp_client.py）](references/mcp_client/)
