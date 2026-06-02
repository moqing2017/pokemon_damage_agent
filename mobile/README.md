# Pokemon Damage Agent Android

This is the Android app version of the Pokemon damage agent, built with Capacitor, React, and TypeScript.

## What is included

- Chat-style damage calculation UI
- User-provided DeepSeek API key in app settings
- No API key is bundled into the APK
- Local bundled data from `data/*.json`
- Local damage calculation with `@smogon/calc`
- DeepSeek-driven term normalization, slot filling, default completion, and context correction
- Native Capacitor HTTP for Android API calls

## Develop

```powershell
cd E:\vscode\project\pokemon_calculater\mobile
npm install
npm run dev
```

## Sync Android

```powershell
cd E:\vscode\project\pokemon_calculater\mobile
npm run android:sync
```

## Build debug APK

Required tools:

- JDK 21
- Android SDK Platform / Build Tools

Installed paths on this machine:

```text
JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.11.10-hotspot
ANDROID_HOME=C:\Users\moqing\AppData\Local\Android\Sdk
```

Build command:

```powershell
cd E:\vscode\project\pokemon_calculater\mobile\android
.\gradlew.bat assembleDebug
```

APK output:

```text
E:\vscode\project\pokemon_calculater\mobile\android\app\build\outputs\apk\debug\app-debug.apk
```

## API key

The APK does not include a DeepSeek API key. Open the app, tap settings in the top-right corner, then fill:

- API Key
- Base URL, default `https://api.deepseek.com`
- Model, default `deepseek-chat`

The key is stored only in local app storage. For a production release, Android encrypted storage is still recommended.
