# GitHub Pages 部署指南

## 🎯 目标
让完整的演示可以通过 `https://ceselia.github.io/TaskPilot/` 直接访问

## 📋 部署步骤

### 1️⃣ 生成演示数据
```bash
cd demo
python3 record_events.py -o data/timeline.json --scenario basic
cd ..
```

### 2️⃣ 创建部署目录结构
GitHub Pages 需要在仓库根目录下创建 `docs/` 目录

```bash
mkdir -p docs/data

# 复制演示数据
cp demo/data/timeline.json docs/data/

# 复制前端页面（重命名为 index.html）
cp demo/web/pages-demo.html docs/index.html
```

### 3️⃣ 配置 GitHub Pages

在仓库设置中：
1. 进入 **Settings** → **Pages**
2. **Build and deployment** 部分：
   - Source: Deploy from a branch
   - Branch: `main` / folder: `/docs`
   - 点击 Save

### 4️⃣ 推送到 GitHub
```bash
git add docs/
git commit -m "Deploy: GitHub Pages demo with timeline data"
git push origin main
```

### 5️⃣ 访问演示
等待 1-2 分钟，访问：
- **https://ceselia.github.io/TaskPilot/**

## ✅ 验证部署

访问后应该看到：
- ✓ 三栏界面（助手、文件系统、邮件客户端）
- ✓ **▶ 开始演示** 按钮可以点击
- ✓ 暂停、重置、速度控制按钮可用
- ✓ 演示数据加载成功

## 🐛 故障排查

### 问题：看不到前端或无法交互

**检查清单：**

1. **检查文件结构**
   ```bash
   ls -la docs/
   # 应该显示：
   # index.html
   # data/
   #   └── timeline.json
   ```

2. **检查 GitHub Pages 配置**
   - Settings → Pages
   - 确保 Source 是 `Deploy from a branch`
   - Branch 是 `main`，folder 是 `/docs`

3. **清理缓存**
   - 按 `Ctrl+Shift+Delete` (Windows) 或 `Cmd+Shift+Delete` (Mac)
   - 清除浏览器缓存后重新访问

4. **检查浏览器控制台**
   - 按 `F12` 打开开发者工具
   - 查看 Console 标签页的错误信息
   - 查看 Network 标签页，检查 `data/timeline.json` 是否加载成功

### 问题：timeline.json 404 错误

**解决方案：**
```bash
# 确保数据文件存在
ls -la docs/data/timeline.json

# 如果文件不存在，重新生成
cd demo
python3 record_events.py -o data/timeline.json
cd ..
cp demo/data/timeline.json docs/data/

git add docs/data/timeline.json
git commit -m "Add timeline data"
git push
```

## 📊 部署架构

```
Ceselia/TaskPilot (GitHub)
├── demo/
│   ├── web/
│   │   └── pages-demo.html (源文件)
│   ├── data/
│   │   └── timeline.json (源文件)
│   ├── record_events.py
│   └── requirements.txt
└── docs/ (GitHub Pages 发布目录)
    ├── index.html (部署版)
    ├── data/
    │   └── timeline.json (部署版)
    └── .nojekyll
```

## 🚀 自动化部署（可选）

如果要实现自动部署，编辑 `.github/workflows/pages.yml`：

```yaml
name: Deploy GitHub Pages

on:
  push:
    branches: [main]
    paths:
      - 'demo/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -r demo/requirements.txt
      
      - name: Generate timeline
        run: |
          cd demo
          python3 record_events.py -o data/timeline.json
          cd ..
      
      - name: Deploy to Pages
        run: |
          mkdir -p docs/data
          cp demo/data/timeline.json docs/data/
          cp demo/web/pages-demo.html docs/index.html
          touch docs/.nojekyll
      
      - name: Push to GitHub
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add docs/
          git commit -m "Auto: Update demo data" || true
          git push
```

## 📝 常见问题

**Q: 为什么页面显示"加载失败"？**
A: 检查 `docs/data/timeline.json` 是否存在。如果不存在，按步骤 1-2 重新生成并上传。

**Q: 修改演示内容后如何更新？**
A: 
1. 修改 `demo/record_events.py` 或后端代码
2. 重新运行 `python3 record_events.py`
3. 复制新的 `timeline.json` 到 `docs/data/`
4. 提交并推送

**Q: 可以自定义演示流程吗？**
A: 可以！修改 `demo/record_events.py` 中的 `record_scenario()` 函数，改变 `scenario` 参数和应答内容。

