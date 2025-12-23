Gemini Swarm Engine (VS Code Edition) 🚀

Gemini Swarm 不是一个简单的聊天机器人，它是寄生在你 IDE 中的 AI 结对编程生命体。
它拥有一颗基于 LangGraph 的独立 Python 大脑，能够感知你的代码上下文、在 Docker 沙箱中自我修正，并直接操控编辑器。

🧠 核心架构 (Hybrid Architecture)

本项目采用 "TypeScript 宿主 + Python 引擎" 的双进程混合架构，结合了 VS Code 的原生交互体验与 Python 生态在 Agent 编排上的强大能力。

graph TD
    subgraph "VS Code Host (TypeScript)"
        UI[Webview Sidebar] <-->|PostMessage| Ext[Extension Main Process]
        Ext -->|Spawn| PythonProc[Python Subprocess]
        Ext -->|Context API| Editor[Active Editor / Diagnostics]
        Ext -->|Action API| Terminal[Integrated Terminal]
    end

    subgraph "The Brain (Python/LangGraph)"
        PythonProc -->|FastAPI| Server[API Server]
        Server <-->|SSE Stream| UI
        Server -->|Graph Run| Agent[Coding Crew]
        
        subgraph "Coding Crew (Agentic Loop)"
            Agent --> Coder
            Coder --> Executor[Sandbox Executor]
            Executor --> Reviewer
            Reviewer -->|Reject| Reflector
            Reflector -->|Fix Strategy| Coder
        end
    end
    
    Executor -.->|Docker API| Docker[Docker Container]


✨ 核心特性

1. 🧬 专用的 Coding Crew 引擎

不同于通用的 LLM 问答，内置的 Python 引擎运行着一个闭环的 LangGraph 状态机：

Coder: 编写代码。

Executor: (可选) 在 Docker 安全沙箱中试运行代码。

Reviewer: 审查代码质量。

Reflector: 如果出错，自动分析根因并制定修复策略，直到代码跑通。

2. 👁️ 上下文感知 (Context Awareness)

AI 不再是盲人。当你发起任务时，插件会自动收集：

文件上下文: 当前文件名、语言、光标行号。

代码选区: 你选中的具体代码片段。

项目结构: 工作区的文件树概览。

诊断信息: 当前文件的报错（红波浪线）。

3. ⚡️ 深度副作用 (Deep Side-Effects)

AI 拥有了“手脚”，可以执行实际操作：

Insert Code: 一键将生成的代码插入光标处或替换选区。

Auto-Fix: 点击代码报错处的“灯泡”，直接召唤 AI 修复 Bug。

Run Terminal: 指挥终端执行 pip install, npm test 等命令。

4. 🛡️ 企业级安全

Docker Sandbox: 代码执行默认在隔离容器中进行（需本地安装 Docker）。

Dependency Isolation: 内置依赖管理，不污染全局 Python 环境。

📦 安装与配置

前置要求

VS Code v1.85+

Python 3.10+ (并将 python 加入 PATH)

Google Gemini API Key (必需)

Docker Desktop (可选，用于启用安全沙箱功能)

快速开始

安装插件: 将 .vsix 文件拖入 VS Code 或在源码目录下按 F5 调试。

配置密钥:
打开 VS Code 设置 (Ctrl+,)，搜索 Gemini Swarm，填入：

Gemini Swarm: Api Key: 你的 Google Gemini API Key。

安装依赖:
按 Ctrl+Shift+P 打开命令面板，运行：

> Gemini: Install Python Dependencies


等待右下角提示“依赖安装成功”。

启动引擎:

> Gemini: Start Engine


侧边栏将自动打开，你现在可以开始对话了！

🎮 使用指南

💬 Mission Control (侧边栏对话)

在输入框描述你的需求，例如："帮我写一个贪吃蛇游戏"。

插入代码: AI 生成代码后，点击代码卡片右上角的 INSERT 📥 按钮，代码将自动写入当前光标位置。

💡 Quick Fix (一键修复)

当编辑器中出现红色波浪线报错时，将鼠标悬停。

点击 "Quick Fix" (或按 Ctrl+.)。

选择 ✨ Fix with Gemini Swarm。

侧边栏会自动激活，读取报错上下文并生成修复代码。

🖥️ 终端交互

你可以要求 AI 执行命令，例如："运行测试并告诉我结果"。

AI 会请求权限在 Gemini Swarm Terminal 中执行 Shell 命令。

🛠️ 开发者指南 (Build & Contribute)

如果你想修改本插件的源码，请遵循以下步骤。

项目结构

.
├── src/                # TypeScript 插件源码 (宿主逻辑)
│   ├── managers/       # 进程、上下文、安全管理器
│   ├── views/          # Webview 提供者
│   └── extension.ts    # 入口文件
├── media/              # Webview 前端源码 (Vue 3 + CSS)
├── python_backend/     # Python 核心引擎 (构建后生成)
├── agents/             # Python Agent 源码 (原始)
├── core/               # Python 核心库
├── package.json        # 插件清单
└── scripts/            # 构建脚本


构建流程

安装 Node 依赖:

npm install


打包 Python 后端:
我们将 Python 源码从根目录移动到 dist/python_backend 以便分发。

npm run package-backend


编译 TypeScript:

npm run compile


打包 VSIX:

npm run package
# 然后使用 vsce package (需安装: npm i -g @vscode/vsce)
vsce package


⚠️ 常见问题

Q: 启动引擎时提示 "Docker 未运行"？
A: 这是为了安全。如果没有 Docker，Coding Crew 将进入 Mock Mode，它依然能写代码，但无法在内部执行和自我测试。请启动 Docker Desktop 以获得完整体验。

Q: 点击 "Install Dependencies" 失败？
A: 请检查你的 python 命令是否可用。你可以在设置中手动指定 Gemini Swarm: Python Path (例如 /usr/bin/python3 或 conda 环境路径)。

Made with ❤️ by Gemini Swarm Team (and a Catgirl AI 🐱)
