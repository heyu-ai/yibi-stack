# Flutter -> TestFlight via GitHub Actions

TestFlight 上傳由 GitHub Actions CI 自動處理。推 git tag 觸發 workflow，
CI 完成 .ipa 建置後上傳 TestFlight。

## 前置條件

| 工具 | 說明 |
|------|------|
| Apple Developer Account | 需有 App Store Connect 權限 |
| App Store Connect API Key | 用於免密碼驗證（取代 Apple ID + 2FA） |
| fastlane | iOS 部署工具（由 CI 執行，本地不需要） |
| Xcode project | 設定好 Bundle ID、signing certificate |

---

## Step 1：建立 App Store Connect API Key

1. 登入 [App Store Connect](https://appstoreconnect.apple.com/access/api)
2. 點選「+」建立新 key，角色選 **App Manager**
3. 下載 `.p8` 金鑰檔（只能下載一次，請妥善保存）
4. 記下：
   - **Key ID**（10 碼英數字）
   - **Issuer ID**（UUID 格式）

---

## Step 2：設定 GitHub Secrets

在 GitHub repository 的 Settings -> Secrets and variables -> Actions 新增：

| Secret 名稱 | 值 |
|-------------|---|
| `APP_STORE_CONNECT_KEY_ID` | Key ID（10 碼） |
| `APP_STORE_CONNECT_ISSUER_ID` | Issuer ID（UUID） |
| `APP_STORE_CONNECT_API_KEY_B64` | `.p8` 檔的 base64 編碼 |

產生 base64 編碼：

```bash
base64 -i AuthKey_XXXXXXXXXX.p8
```

---

## Step 3：建立 GitHub Actions Workflow

建立 `.github/workflows/release-ios.yml`：

```yaml
name: Release iOS to TestFlight

on:
  push:
    tags:
      - 'v*'

jobs:
  build-ios:
    runs-on: macos-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Flutter
        uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.x'
          channel: 'stable'

      - name: Setup Ruby / fastlane
        uses: ruby/setup-ruby@v1
        with:
          ruby-version: '3.2'
          bundler-cache: true
          working-directory: ios

      - name: Flutter pub get
        run: flutter pub get

      - name: Build iOS IPA
        run: flutter build ipa --release --export-options-plist=ios/ExportOptions.plist

      - name: Upload to TestFlight
        working-directory: ios
        env:
          APP_STORE_CONNECT_KEY_ID: ${{ secrets.APP_STORE_CONNECT_KEY_ID }}
          APP_STORE_CONNECT_ISSUER_ID: ${{ secrets.APP_STORE_CONNECT_ISSUER_ID }}
          APP_STORE_CONNECT_API_KEY_B64: ${{ secrets.APP_STORE_CONNECT_API_KEY_B64 }}
        run: bundle exec fastlane beta
```

---

## Step 4：設定 fastlane

### Gemfile（`ios/Gemfile`）

```ruby
source "https://rubygems.org"

gem "fastlane"
```

### Fastfile（`ios/fastlane/Fastfile`）

```ruby
default_platform(:ios)

platform :ios do
  desc "Build and upload to TestFlight"
  lane :beta do
    api_key = app_store_connect_api_key(
      key_id: ENV["APP_STORE_CONNECT_KEY_ID"],
      issuer_id: ENV["APP_STORE_CONNECT_ISSUER_ID"],
      key_content: ENV["APP_STORE_CONNECT_API_KEY_B64"],
      is_key_content_base64: true,
    )

    upload_to_testflight(
      api_key: api_key,
      ipa: "../build/ios/ipa/Runner.ipa",
      skip_waiting_for_build_processing: true,
    )
  end
end
```

### ExportOptions.plist（`ios/ExportOptions.plist`）

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>app-store</string>
  <key>uploadBitcode</key>
  <false/>
  <key>uploadSymbols</key>
  <true/>
</dict>
</plist>
```

---

## Step 5：在本地測試 fastlane（選用）

```bash
cd ios
bundle install
bundle exec fastlane beta
```

本地執行需要 macOS + Xcode + 有效的 distribution certificate。
CI 上通常已有 signing 設定，本地測試非必要。

---

## 常見問題

| 問題 | 解法 |
|------|------|
| `No signing certificate` | Xcode 設定 Automatic Signing，或在 CI 匯入 certificate |
| `Invalid API key` | 確認 `.p8` 內容已正確 base64 編碼，Key ID 和 Issuer ID 無誤 |
| `No profiles for bundle ID` | 確認 App Store Connect 已建立 App 並設定 Bundle ID |
| `flutter build ipa` 失敗 | 確認 `ExportOptions.plist` 存在且 `method` 設為 `app-store` |
| TestFlight 24 小時後才出現 | Apple 審核最久可達 24 小時，`skip_waiting_for_build_processing: true` 不會等待 |
| 要追蹤建置進度 | `gh run watch <run-id>`，或至 GitHub Actions 頁面查看 |

---

## 參考資源

- [Flutter 官方 iOS 部署指南](https://docs.flutter.dev/deployment/ios)
- [fastlane pilot 文件](https://docs.fastlane.tools/actions/pilot/)
- [App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi)
