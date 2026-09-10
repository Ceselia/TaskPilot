#!/bin/bash
# 构建 GitHub Pages 部署包

set -e

echo "📦 构建 GitHub Pages 部署包..."

# 创建部署目录
DEPLOY_DIR="docs"
mkdir -p "$DEPLOY_DIR"

# 1. 生成 timeline.json
echo "1️⃣ 录制演示事件流..."
cd demo
python3 record_events.py -o data/timeline.json --scenario basic
cd ..

# 2. 复制 HTML 和 JavaScript
echo "2️⃣ 复制前端文件..."
cp demo/web/pages-demo.html "$DEPLOY_DIR/index.html"
cp demo/web/timeline-player.js "$DEPLOY_DIR/"

# 3. 复制 timeline.json
echo "3️⃣ 复制数据文件..."
mkdir -p "$DEPLOY_DIR/data"
cp demo/data/timeline.json "$DEPLOY_DIR/data/"

# 4. 创建 .nojekyll（禁用 Jekyll 处理）
echo "4️⃣ 配置 GitHub Pages..."
touch "$DEPLOY_DIR/.nojekyll"

# 5. 创建 README
cat > "$DEPLOY_DIR/README.md" << 'EOF'
# TaskPilot 演示

这是 TaskPilot 的完整流程演示。

## 本地查看

1. 启动简单 HTTP 服务器：
   ```bash
   python3 -m http.server 8000 --directory docs
   ```

2. 打开浏览器访问 http://localhost:8000

## GitHub Pages 部署

此目录已配置为 GitHub Pages 发布源，自动部署到 `https://ceselia.github.io/TaskPilot/`

## 文件说明

- `index.html` - 演示 UI 主页
- `timeline-player.js` - 回放引擎
- `data/timeline.json` - 预录制的事件时间轴
EOF

echo "✅ 构建完成！"
echo ""
echo "📂 部署目录：$DEPLOY_DIR"
echo "📄 文件列表："
ls -la "$DEPLOY_DIR"
echo ""
echo "🚀 下一步："
echo "  git add $DEPLOY_DIR"
echo "  git commit -m 'Deploy: GitHub Pages demo'"
echo "  git push"
