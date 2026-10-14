# PRIS：个人研究情报系统

## 云端版

云端 Research Desk 使用带 ChatGPT 登录保护的 Sites 网页与 D1 数据库，电脑和手机可访问同一 HTTPS 地址。
Python 采集与分析流程由私有 GitHub 仓库的 Actions 执行；网页负责日报、论文、偏好、研究对话和阅读状态。
网页点击“生成新知”会进入云端队列，下一次 GitHub 调度处理。调度并非实时保证。

每天目标为北京时间 00:30 生成新知；每 30 分钟检查反馈和网页任务队列。
云端流程启用后应停用 Windows 同名日报和反馈任务，避免重复推送与多个 Telegram 消费者。
GitHub Actions 可能因服务调度而延迟，需关注仓库 Actions 状态和网站运行记录。

云端密钥配置：

- Sites 加密环境配置：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`PRIS_RUNNER_TOKEN`
- GitHub Actions Secrets：原有 DeepSeek、Telegram、Zotero 凭据，以及 `PRIS_CLOUD_URL`、`PRIS_SITE_ACCESS_TOKEN`、`PRIS_RUNNER_TOKEN`
- GitHub Actions Variables：配置完成后设 `PRIS_CLOUD_ENABLED=true`

部署前用 `python -m pris.cloud --root . --initial-upload` 导入本人授权的研究记录、日报和偏好。
后续同步不覆盖已修改的云端偏好。网页修改会被 Python 运行节点拉取并用于下一次推荐。
原始 PDF 和本机密钥不进入网页、数据库或 Git 源码。云端对话只发送问题、当前偏好与主动选中的论文摘要/解读至 DeepSeek。
日报可下载 Markdown 并导入本地 Obsidian，GitHub Actions 也保留短期 Markdown 运行产物。

`cloud/` 是云端网页源码镜像；托管版本由 Sites 源码工作流发布，GitHub 主仓库用于项目留存。

PRIS 每晚发现和筛选经济学、AI及少量社会人文内容，调用 DeepSeek 生成中文简报，通过 Telegram 推送，并将完整 Markdown 保存到 Obsidian。只有用户明确要求深读的文献才会进入 Zotero。

## Research Desk 管理界面

PRIS 有一个直接连接本地数据库与 Obsidian 的网页工作台。打开后可以：

- 查看研究概览、全部历史日报和费用记录
- 搜索标题、DOI、英文摘要或已有中文解读；收藏、标记已读、选择深读、记录评价
- 自由增删经济学、AI、社会人文的子主题；修改领域配比、每日数量、排除词与来源开关
- 调整论文、宏观动态和 AI 解读风格，保留必要数学
- 与 PRIS 的 DeepSeek 助理对话；讨论选中的论文或提出偏好调整，查看方案后点击应用
- 查看 Telegram 反馈、偏好变更历史并恢复到旧版本
- 按需生成新日报、同步反馈和处理已选深读条目

Windows 下双击 `Open-PRIS.cmd`，或在项目目录执行：

```powershell
python -m pris.app --root . ui
```

然后打开 `http://127.0.0.1:8765`。界面仅监听本机，手机仍以 Telegram 推送为主。
如需登录 Windows 后自动启动界面：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-desktop-task.ps1
```

界面偏好保存在 `data/preferences.json`，每日任务启动时自动读取，优先于基础 `config.toml`；
历史日报不重新改写。初次保存后，配额按界面领域份额自动计算（余数分配到最接近的整数）。
添加子主题会更新检索关键词；新领域的数据采集器仍需配置相应来源。

对话会向 DeepSeek 发送问题、近期对话、当前偏好，以及你主动选择的论文摘要与已有解读；
不会上传整库、密钥或全部 PDF。回答仅基于这些上下文。对话不执行系统命令、修改运行时间或检索未提供的全文。
界面保存的反馈和对话记录保存在本地 SQLite；自然语言偏好方案只有点击“应用”后生效。
来源验证与模型费用估算仍有各自的限制，费用以服务商账单为准。

## 当前已实现

- 追踪经济学五大刊、NBER当前工作论文接口和重点 AI arXiv 分类
- 追踪国家统计局、BIS、OpenAI与Hugging Face等官方信息流
- 个人兴趣关键词与领域权重配置
- Crossref DOI与标题交叉核验
- arXiv主标识核验；没有 DOI 时明确标记
- DeepSeek 排序和摘要，失败时保守降级为本地排序
- 重点条目按研究问题、背景、文章结构、方法、必要数学、发现、贡献和局限完整讲解
- 默认每日 10 条完整解读、5 条快速动态，数量与比例可通过界面调整
- Obsidian Markdown 日报
- Telegram 推送、自然语言反馈和深读按钮
- 深读条目的书目信息与“等待全文”笔记
- 只有深读条目才通过 Zotero Web API 写入 `PRIS 深度阅读`
- SQLite 去重、状态、反馈和模型费用记录
- 双电脑单运行节点保护
- Windows 每天 00:30 夜间任务、每15分钟反馈轮询，以及登录时启动的本地界面

## 数据流

```text
权威来源 → 元数据筛选 → DOI/主标识核验 → DeepSeek判断
    → Telegram简报 + Obsidian日报
    → 用户要求深读 → Zotero书目 + 等待用户提供PDF
```

系统不会在没有全文时假装读过正文。没有通过真实性核验的条目不会进入每日推荐。

## 第一次配置

在本目录打开 PowerShell：

```powershell
python -m pip install -e .
Copy-Item .env.example .env
Copy-Item config.example.toml config.toml
```

编辑 `.env`，填写：

```text
DEEPSEEK_API_KEY=DeepSeek密钥
TELEGRAM_BOT_TOKEN=BotFather提供的Token
TELEGRAM_CHAT_ID=你的Telegram Chat ID
ZOTERO_API_KEY=Zotero专用API Key
ZOTERO_USER_ID=Zotero数字用户ID
PRIS_RUNNER_ID=primary
```

`.env` 不会被 Git 记录，也不应放在两台电脑的同步目录中。

运行检查：

```powershell
python -m pris.app --root . doctor
```

手动运行一次日报：

```powershell
python -m pris.app --root . run
```

结果默认写到：

```text
vault/PRIS/01 每日简报/
```

可以在 `config.toml` 中把 `system.vault` 改成真实 Obsidian Vault 内的相对或绝对位置。当前实现将相对路径解释为 PRIS 项目目录下的路径。

## Telegram

1. 在 Telegram 联系 `@BotFather`，创建私人 Bot并获取 Token。
2. 给 Bot 发送一条消息。
3. 获取自己的 Chat ID并填入 `.env`。
4. 执行 `poll-feedback` 后，系统会只接受配置 Chat ID 发来的消息。

支持：

- 点击“深读 2”
- 回复“深读第2篇”
- 直接发送自然语言评价

自然语言评价原文保存在 SQLite 和：

```text
vault/PRIS/06 反馈记录/
```

## Zotero

在 Zotero 账号设置中创建一个只供 PRIS 使用的 API Key，允许读写个人资料库。PRIS只上传书目元数据，不上传PDF附件。

写入规则：

- 普通推荐：绝不写入
- 点击深读或发送深读指令：生成等待全文笔记
- Zotero配置有效：加入 `PRIS 深度阅读` 集合
- 已有同 DOI或同标题条目：不重复添加

用户获得PDF后，在主电脑上将其拖入对应 Zotero 条目，再交给 PRIS做基于全文的分析。

## 双电脑部署

两台电脑可以都复制此项目，但同一时刻只允许一台执行日报。

```toml
[system]
active_runner_id = "research-laptop"
```

在实际运行电脑的 `.env` 中设置：

```text
PRIS_RUNNER_ID=research-laptop
```

另一台电脑使用不同的 `PRIS_RUNNER_ID`，即使误触定时任务也会安全退出。建议同步以下内容：

- `config.toml` 和 `data/preferences.json`
- `data/pris.db`
- Obsidian中的 `PRIS` 文件夹

不要同步 `.env`。SQLite数据库不适合两台电脑同时写入，因此只允许活动节点运行；知识电脑主要阅读和整理。

## 安装Windows定时任务

确认手动运行成功后，以当前用户执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-scheduled-tasks.ps1
```

它会创建：

- `PRIS Nightly Research`：每天 00:30，允许唤醒电脑
- `PRIS Telegram Feedback`：每15分钟读取一次反馈

安装定时任务会修改 Windows 任务计划程序，因此应在凭据全部测试通过后执行。

## 来源与扩展

`config.toml` 中可以随时增加：

- Crossref期刊 ISSN
- RSS/Atom源
- arXiv分类和关键词
- 兴趣词、排除词及领域权重

当前版本首先验证核心链路。后续来源层将继续加入中国宏观官方信息、国际机构报告、CEPR/RePEc以及 AI 实验室官方发布，并保持“来源类型和证据状态明确标记”。

## GitHub 留存与个人数据

Git 仓库保存程序、界面、示例配置、脚本和测试。`.env`、`config.toml`、`data/`、`vault/`、临时 PDF 和日志均被忽略。
因此 GitHub 是代码备份，不是个人研究库备份。数据库与 Obsidian 请另行备份；密钥只留在各自电脑。

模型只负责分析与对话，采集、存储和输出独立运行。当前适配 DeepSeek 的 OpenAI 兼容接口；
其他提供商可能需要调整 thinking 等特定参数，并不是任意 API 地址都可以直接替换。

## 测试

```powershell
python -m unittest discover -s tests -v
```
