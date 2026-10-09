<div align="center">

# 🛡️ 个人信息复核器（PII Review）

**文档进入知识库前，定位疑似个人信息，逐项人工复核后导出脱敏版与审计清单。**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](#环境要求)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-25%20passed-34C759?style=flat-square)](#测试)
[![Zero Dep](https://img.shields.io/badge/核心-零依赖-8E8E93?style=flat-square)](#快速开始)

</div>

---

## 这是什么

一个**本地可运行的脱敏复核工具**，服务对象是维护企业知识库的资料管理员与审核人。

资料上传培训材料、客户沟通样例或售后记录时，先自动识别电话号码、证件号、姓名、地址等疑似个人信息；审核人查看**原文位置、拟处理方式与例外原因**，逐项决定遮盖 / 替换 / 保留 / 误报，最后导出脱敏版与审计清单。

> 本项目提供**复核辅助**，不作完整合规认证；人工审核仍是发布前的责任点。

## 解决什么问题

| 日常困难 | 这个工具给你 |
|---|---|
| 不知道文档里自动检测到了什么、遗漏在哪 | 规则识别 + 可替换识别器，逐项标注**命中位置**与置信 |
| 自动识别不敢全信 | 区分「**高把握命中**」与「**需人工判断**」，不默认删除所有数字 |
| 谁确认、为什么这么处理，说不清 | 逐项记录**处理方式 + 理由 + 复核时间**，导出审计清单 |
| 原始资料 / 脱敏版 / 审核记录对不上 | 三者按文件摘要（SHA256）对应，可追溯 |

## 快速开始

```bash
git clone https://github.com/lizilong0326/pii-review.git
cd pii-review

# 命令行模式：导入 20 份合成样本中的一份并检测
python -m pii_review import data/samples/s01.json

# Web 复核界面（左右对照）
python -m pii_review serve --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

> **环境要求**：Python 3.10+，核心**零依赖**（仅标准库）。真实 PDF/DOCX/图片解析需可选依赖（见下）。

## 识别能力与置信分级

| 类型 | 高把握命中 | 需人工判断 |
|---|---|---|
| 电话 | `13800138000` 精确匹配 | 连字符、断行、OCR 错字 |
| 证件号 | 18 位 / 15 位精确匹配 | OCR 错字（如 `l`→`1`、`O`→`0`） |
| 姓名 | — | 「姓名：张三」、姓氏 + 称谓 |
| 地址 | — | 「地址/位于」引导词、省市区结构 |

关键边界：**不默认删除所有数字** —— 订单号、产品编号、日期等普通编号不会被误标。

## 左右对照复核

Web 界面左栏展示**原文（候选高亮）**，右栏展示**脱敏预览**；每个候选可逐项选择：

- **遮盖** / **替换** / **保留** / **误报**，并填写理由；
- 批量操作（如「全部遮盖」）也**逐项落盘**，保留逐条记录。

## 导出与审计清单

导出产物（`out/`）：

- `*.redacted.txt` —— 脱敏文件（`[已遮盖:电话]` 等占位符）
- `*.audit.json` —— 机器可读审计清单
- `*.audit.html` —— 可阅读审计清单

审计清单字段：**文件摘要（SHA256）、规则版本、处理项、复核时间、结果**；未处理项、解析失败页、低置信候选均有醒目标记，**导出不阻断，仅标记**。

## 断点续跑与重复导入

- 状态存于 `.state/<sha256>/`，中断恢复**不会把未审核项误标为已通过**；
- 同一文件重复导入按 **SHA256** 识别，提示「已存在记录」；
- 清理动作（删除本机状态/临时文件）属破坏性操作，需显式确认。

## 回归题集

`data/samples/` 含 **20 份合成样本**（电话 / 证件号 / 地址 / 普通编号 / OCR 错字），重点覆盖断行电话、OCR 错字、同名实体、地址上下文：

```bash
python -m pii_review regression
# 召回率：100.00%（17/17）  误报率：0.00%
```

## 项目结构

```
pii-review/
├── pii_review/
│   ├── models.py        # 数据模型（文档/块/候选/决策/状态）
│   ├── detectors.py     # 规则识别器（电话/证件号/姓名/地址，置信分级）
│   ├── parsers.py       # 解析适配层（JSON样本/文本 + Docling/PaddleOCR 真实实现）
│   ├── state.py         # 状态持久化、断点续跑、重复导入
│   ├── redact.py        # 脱敏应用与醒目标记
│   ├── audit.py         # 审计清单（JSON + HTML）
│   ├── pipeline.py      # 核心流程
│   ├── webui.py         # 本地 Web 复核界面（stdlib，零依赖）
│   └── cli.py           # 命令行入口
├── data/
│   ├── samples/         # 20 份合成样本（JSON 已解析结构）
│   └── ground_truth.json # 漏检/误报标注
├── tests/               # 16 个测试
└── README.md
```

## 漏检边界（README 与演示视频说明口径）

- 规则只覆盖**电话、证件号、姓名、地址的常见形态**；
- **隐含个人信息**（如病历、薪资、非标格式）可能不符合规则而漏检；
- **OCR 丢字**会漏检，错字命中会标为「需人工判断」；
- 人工审核仍是发布前的责任点；本项目**不承诺 100% 脱敏**。

## 可选依赖（真实文档解析）

| 能力 | 依赖 | 安装 |
|---|---|---|
| PDF / DOCX 结构解析 | [Docling](https://github.com/docling-project/docling) | `pip install docling` |
| 图片 OCR | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | `pip install paddleocr paddlepaddle` |

两类解析器均已实现并归一为 `Document`（页 → 块 + 坐标）；依赖未安装时，导入对应格式会给出**显式错误提示**，不会静默跳过。组件各自的模型文件与依赖许可须在选定版本后核查。

## 测试

```bash
python -m pytest tests/ -q
```

覆盖：识别器单元测试（含断行电话、OCR 错字、普通编号不误报）、核心流程（导入/导出/断点恢复/重复导入）、20 份样本漏检误报回归。

## License

[MIT](LICENSE) © 2026 lizilong0326
