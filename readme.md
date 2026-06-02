# 宝可梦伤害计算 Agent

一个面向宝可梦对战场景的自然语言伤害计算工具。用户可以直接用中文提问，例如：

```text
晴天下的幽尾玄鱼波动冲能一招打死喷火龙Y吗？
藏玛然特被威吓一次后能一下扑击打死仆刀将军吗？
```

项目会先把自然语言问题解析成结构化战况，再调用本地伤害计算器输出伤害范围和击杀结论。

## 核心特点

- 支持中文自然语言输入
- 支持宝可梦、招式、道具、特性名称的中英文映射
- 支持错别字、别名、口语表达的术语标准化
- 支持多轮上下文修正，例如用户补充“不是暗影球，是波动冲”
- 支持必要信息追问和未知信息默认补全
- 支持 Android APK，用户在应用内自行填写 DeepSeek API Key
- 伤害结果由 `@smogon/calc` 本地计算，不由 LLM 编造

## 工作流程

```text
用户中文问题
  ↓
DeepSeek 术语标准化
  ↓
DeepSeek 槽位抽取与战况解析
  ↓
必要信息追问 / 默认配置补全
  ↓
@smogon/calc 本地伤害计算
  ↓
中文输出完整配置、伤害范围、击杀结论
```

LLM 负责理解用户意图和补全配置，确定性计算器负责真正的伤害数值。

## 项目结构

```text
pokemon_calculater/
├── agent.py                  # 命令行版 Agent
├── data/                     # 宝可梦、招式、道具、特性映射和效果数据
├── tools/
│   ├── calc.mjs              # Node 版伤害计算入口
│   └── build-name-maps.mjs   # 数据映射生成脚本
├── mobile/                   # Android 应用工程
├── package.json              # Node 依赖
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量示例
└── readme.md
```

## 命令行版本

### 1. 安装依赖

```powershell
pip install -r requirements.txt
npm install
```

### 2. 配置 DeepSeek

复制 `.env.example` 为 `.env`，然后填写自己的 API Key：

```text
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_MODEL=deepseek-chat
BASE_URL=https://api.deepseek.com
```

`.env` 已经被 `.gitignore` 忽略，不要上传到 GitHub。

### 3. 启动

```powershell
python agent.py
```

可用命令：

- `exit`：退出
- `reset`：清空上下文
- `status`：查看当前战况

## Android 应用

Android 工程位于 `mobile/`。

已实现：

- 对话式中文界面
- 应用内填写 DeepSeek API Key
- API Key 不打包进 APK
- APK 内本地运行 `@smogon/calc`
- 支持上下文修正和中文计算结果展示

本地 debug APK 输出位置：

```text
mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

如果需要给别人下载，推荐把 APK 上传到 GitHub Releases，不建议直接提交到 git 仓库。

## Android 打包

进入移动端目录：

```powershell
cd mobile
npm install
npm run android:sync
```

构建 debug APK：

```powershell
cd android
.\gradlew.bat assembleDebug
```

需要本机安装：

- JDK 21
- Android SDK Platform / Build Tools

## 数据更新

重新生成宝可梦、招式、道具、特性映射：

```powershell
node tools\build-name-maps.mjs
```

生成的数据会写入 `data/` 目录。

## 安全说明

本项目不会在源码或 APK 中内置 DeepSeek API Key。

- 命令行版从 `.env` 读取 API Key
- Android 版由用户在应用设置中填写 API Key
- `.env`、APK、构建产物、`node_modules` 均已加入 `.gitignore`

上传 GitHub 前可以检查：

```powershell
git status --ignored --short
```

## 技术栈

- Python
- Node.js
- React
- TypeScript
- Capacitor
- DeepSeek API
- `@smogon/calc`

## 适合作为秋招项目展示的点

- LLM Agent 与确定性工具调用结合
- 中文对战术语标准化
- 多轮上下文槽位更新
- 道具、特性、天气、场地等复杂条件建模
- CLI 到 Android APK 的完整工程落地
