# 提交图标到 Home Assistant Brands

当前插件的图标在本地可以显示，但如果要让图标通过官方 CDN 加载（`https://brands.home-assistant.io/_/sxgjdl_power/icon@2x.png`），需要提交到 HA 官方 brands 仓库。

## 提交步骤

### 1. Fork 官方仓库
https://github.com/home-assistant/brands

### 2. 创建品牌目录
在你 fork 的仓库里创建：
```
custom_integrations/sxgjdl_power/
├── icon.png        (256x256)
├── icon@2x.png     (512x512)
└── manifest.json
```

### 3. 复制文件
将本仓库 `.github/brands/sxgjdl_power/` 下的三个文件复制到上述目录。

### 4. 提交 Pull Request
- 标题：`Add sxgjdl_power integration icon`
- 说明：简短介绍这是山西地电用电查询集成的图标

### 5. 等待审核
官方团队会审核你的 PR，通常需要几天到几周。

## 审核通过后

图标会自动托管在：
- `https://brands.home-assistant.io/_/sxgjdl_power/icon.png`
- `https://brands.home-assistant.io/_/sxgjdl_power/icon@2x.png`

所有安装你插件的用户都会自动从 CDN 加载图标，无需等待插件更新。

## 临时方案

在官方审核期间，插件会使用本地的 `icon.png`，用户体验不受影响。
