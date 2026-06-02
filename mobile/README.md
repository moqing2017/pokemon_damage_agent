# 宝可梦伤害计算 Agent Android 版

这是宝可梦伤害计算 Agent 的 Android 应用工程，使用 Capacitor + React + TypeScript 构建。

## 功能说明

Android 版提供一个对话式界面，用户可以直接输入中文对战问题：

```text
晴天下幽尾玄鱼波动冲能确一喷火龙Y吗？
```

应用会完成：

- 中文术语标准化
- 宝可梦、招式、道具、特性槽位抽取
- 必要信息追问
- 常见配置默认补全
- 本地伤害计算
- 中文结果展示

伤害计算由 APK 内置的 `@smogon/calc` 完成，不由 LLM 直接生成伤害数字。

## API Key 机制

APK 不内置 DeepSeek API Key。

首次打开应用后，点击右上角设置按钮，填写：

- API Key
- Base URL，默认 `https://api.deepseek.com`
- Model，默认 `deepseek-chat`

API Key 只保存到当前手机的应用本地存储中。生产环境如果要进一步增强安全性，可以接入 Android 加密存储。

## 目录结构

```text
mobile/
├── android/              # Capacitor 生成的 Android 原生工程
├── src/
│   ├── App.tsx           # 移动端界面
│   ├── agent.ts          # Agent 流程编排
│   ├── calc.ts           # @smogon/calc 本地计算适配
│   ├── deepseek.ts       # DeepSeek 请求封装
│   ├── storage.ts        # 本地设置存储
│   ├── data.ts           # 数据映射加载
│   └── data/             # 打包进 APK 的 JSON 数据
├── capacitor.config.ts
├── package.json
└── README.md
```

## 本地开发

```powershell
cd E:\vscode\project\pokemon_calculater\mobile
npm install
npm run dev
```

浏览器访问：

```text
http://127.0.0.1:5173
```

## 同步 Android 工程

修改前端代码后，同步到 Android：

```powershell
cd E:\vscode\project\pokemon_calculater\mobile
npm run android:sync
```

## 构建 debug APK

需要安装：

- JDK 21
- Android SDK Platform / Build Tools

当前机器已配置：

```text
JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot
ANDROID_HOME=C:\Users\moqing\AppData\Local\Android\Sdk
```

构建命令：

```powershell
cd E:\vscode\project\pokemon_calculater\mobile\android
.\gradlew.bat assembleDebug
```

APK 输出位置：

```text
E:\vscode\project\pokemon_calculater\mobile\android\app\build\outputs\apk\debug\app-debug.apk
```

## 发布 APK

不建议把 APK 直接提交到 git 仓库。

推荐流程：

1. 在 GitHub 仓库进入 `Releases`
2. 创建新版本，例如 `v0.1.0`
3. 上传 `app-debug.apk`
4. 勾选 `Pre-release`
5. 发布

## 注意事项

- `mobile/android/local.properties` 是本机 SDK 路径，已被忽略，不应上传
- `mobile/dist/` 和 Android build 产物已被忽略
- `app-debug.apk` 是构建产物，已被忽略
- 如果要发正式版，需要配置 release 签名和混淆策略
