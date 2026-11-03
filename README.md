# 面试搭子 interview-buddy

一个 AI 模拟面试 + 知识库问答的 Web 应用。上传自己的学习资料，让 AI 基于资料出题、追问、打分，帮你练习技术面试。

## 功能

- **知识库问答（RAG）**：上传 `.md` / `.txt` 资料，AI 基于你的资料回答，并标注来源。
- **模拟面试**：可选面试方向（如"RAG"），AI 面试官出题 → 追问 → 结束打分，全程可刷新恢复进度。
- **面试复盘**：按题分组回看整场面试的完整一问一答。
- **错题题库**：把面试中想收藏的题存进题库，支持分类、删除、修改分类。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + Python 3.11 |
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS |
| 生成 | DeepSeek（`deepseek-chat`） |
| 向量化 | 智谱 AI（`embedding-3`），内存向量库 + 余弦相似度检索 |
| 存储 | SQLite（题库） |

## 项目结构

```
interview-buddy/
├── main.py            # FastAPI 入口，所有接口
├── src/               # 后端核心模块
│   ├── rag.py         # RAG 问答
│   ├── interview.py   # 模拟面试流程
│   ├── bank.py        # 题库（SQLite）
│   ├── embedding.py   # 智谱向量化
│   ├── vector_store.py# 内存向量库 + 余弦检索
│   ├── document_loader.py # 文档读取与切分
│   └── config.py      # 配置与路径
├── tests/             # 后端测试
├── data/docs/         # 资料文件（.md/.txt，运行时生成）
└── web/               # 前端（React + Vite）
```

## 快速开始

### 前置条件

- Python 3.11
- Node.js 18+
- 两个 API Key（见下方"配置"）

### 1. 配置环境变量

复制模板并填入真实 Key：

```bash
# macOS / Linux
cp .env.example .env

# Windows（PowerShell / CMD）
copy .env.example .env
```

`.env` 里需要两个 Key：

| 变量 | 用途 | 申请地址 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 生成回答 | https://platform.deepseek.com |
| `ZHIPU_API_KEY` | 向量化（embedding） | https://open.bigmodel.cn |

> 为什么用智谱做 embedding？DeepSeek 官方目前不提供 embedding 接口，所以向量化单独用智谱的 `embedding-3` 模型。

### 2. 启动后端

```bash
# 创建并激活虚拟环境
python3.11 -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动（默认 http://localhost:8000）
uvicorn main:app --reload
```

启动后可访问 http://localhost:8000/docs 查看接口文档。

### 3. 启动前端

```bash
cd web
npm install
npm run dev
```

前端默认运行在 http://localhost:5173，已配置代理把 `/api` 请求转发到后端 8000 端口。

### 4. 使用

1. 打开前端 → 「知识库」页面上传 `.md` / `.txt` 资料（自动构建知识库）。
2. 「问答」页面向资料提问。
3. 「面试」页面选个方向开始模拟面试。

## 测试

```bash
pytest
```

## 检索质量评测

切分粒度不是拍脑袋定的，是评测出来的。`eval/` 下有一套可复现的检索评测：

```bash
python eval/run_recall_eval.py                    # 扫描 300 / 500 / 800 三档
python eval/run_recall_eval.py --chunk-sizes 300  # 只跑一档
```

评测口径：

- 语料固定为 `eval/corpus/` 的快照，改线上资料不会影响历史分数
- 切分与检索**复用生产代码**（`split_text` / `VectorStore.search`），测的就是线上那条链路
- 每道题标注一段原文片段，Top-K 结果里出现该片段即算命中 —— 判定不看人、不看模型输出，换台机器跑结果一致

当前结果（20 题 / 2 篇 / 85789 字）：

| chunk_size | overlap | chunks | Recall@1 | Recall@4 | MRR@6 |
|---|---|---|---|---|---|
| 300 | 30 | 318 | 50% | **100%** | 0.729 |
| 500 | 50 | 192 | 30% | 95% | 0.571 |
| 800 | 80 | 120 | 55% | 95% | 0.738 |

结论：原来的默认值 500 字反而是三档里最差的（正好卡在「一个知识点说不完、两个又混进来」的粒度上），
已改为 300 / 30。800 的 Recall@1 略高，但单块 800 字会把无关内容一起塞进上下文，且丢掉了 1 道题。

## 首字延迟（TTFT）

流式不是玄学，量一下就知道省了多少等待：

```bash
uvicorn main:app --port 8000    # 先起服务
python eval/measure_ttft.py     # 同批问题分别走流式与非流式
```

实测（5 个问题 × 2 轮，本机回环）：检索完成 0.61s、**首字 1.33s（P50）**、整段 2.12s；
非流式整段 1.98s。

值得注意的是：**流式的整段耗时反而比非流式慢约 0.14s**（SSE 有额外开销）。
流式买的从来不是总时长，而是"1.33s 就开始出字"的感知等待 —— 相比阻塞式的 1.98s 缩短约 33%。
回答越长，这个差距越大。

## 许可证

[MIT](./LICENSE)
