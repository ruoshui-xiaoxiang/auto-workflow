# auto-workflow — 本地模型自动化工作流框架

> **⚠ 快照时效（11-04 对账）**：本文件"当前状态"段是 **2026-09-04** 的快照，多处已与现役不符。
> 现役真源以 `D:\AIWorkflow\官方路径.json` 与手册 `E:\本地工作流规范手册\20_通用规范层\` 为准。
> 已就地更正的现役事实：**代码根 `D:\AIWorkflow\engine\`**（不是 `E:\LocalAI\workflows\`）；
> **8787 webui 与 8790 说话出片 UI 已废**；**交付根由 `pool_root\项目\批次` 派生**（`E:\FLUX_Workflow\out\` 盘上已无）；
> **`auto_draft`/`t_auto`/`vl_score_image` 已于 11-04 整条退役**（审美判定交给人，桩在 `workflows/auto_draft.yaml`，
> `run.py auto_draft` 打印原因并以 78 退出）；**VL key 文件 `E:\密钥文件\阿里多模态.txt` 盘上不存在**
> ⇒ 一切 `vl_*` 恒 disabled（不是"通过"，是未启用）。
> 下面带日期的「### 2026-09-03 ｜…」等变更日志**保留原话不改**——那是当时的举证，改了就是篡改。

## 基础信息

- 项目名：auto-workflow
- 代码根：`D:\AIWorkflow\engine\` 〔11-04 更正：原写 `E:\LocalAI\workflows\`，该路径盘上已无；
  唯一编排入口 `cd D:\AIWorkflow\engine && python run.py <workflow>`〕
- 定位（一句话）：基于本地服务（llama.cpp 五档 + ComfyUI）的模块化自动化编排框架——一个 YAML = 一个工作流；2026-09-03 起长成「网页操作台 + 云端 LLM/VL + 闭环自动出图」的自用流水线
- 当前版本 / 里程碑：webui v1（C 方案：先自用后交人）+ agent 最小闭环（t_auto）+ 分发版 v0.1（GitHub + Inno Setup 安装包 + 云服务器部署）
- 最新更新：2026-11-04 14:18
  （11-04 对账：代码根／模板／日志／产物路径按现役更正，`auto_draft`＋`vl_*` 标退役，
  VL key 文件核实盘上不存在；带日期的变更日志保留原话不改。注：`build_index.py` 的 STAMP 是
  行尾锚定严格式，括注只能另起一行，写在时间戳后面会被判「缺少字段」）
- 摘要：WebUI 操作台（8787）+ 双云端后端 + 云端 VL 判分 + t_auto 闭环自动出图已建成并实跑成功；2026-09-04 完成 GitHub 仓库推送（ruoshui-xiaoxiang/auto-workflow，26 文件 4138 行，敏感信息审查通过）、Inno Setup 安装包编译（2.1MB exe）、SCP 部署到云服务器（/opt/product-site/downloads/，网站可下载）；云端账号仍不可用（包月 ~09-06 重置、按量需充值），本地兜底链不受影响。晚间修复网页操作台启动器（残留实例占口致不弹页，改幂等复用）+ 引擎 HTTP 全量代理免疫（trust_env=False），LLM 兜底链全路径实测通过（冷启动/热重启/坏后端跳过/云端无 key 跳过）

## 当前状态（快照）

- 结构：`run.py`（引擎）+ `tasks.py`（任务插件：llm/comfyui/files/shell/auto）+ `webui.py`（网页操作台，纯 stdlib，零外部依赖）+ `config.yaml`（后端注册与兜底链）+ `workflows\*.yaml` + `comfy\*.json`
- **WebUI 操作台**：http://127.0.0.1:8787（桌面快捷方式自动拉起），只读壳 + 子进程调 run.py；一键运行/停止、实时进度（读 status.json，不依赖下拉选择）、历史批次倒序、ComfyUI 原版页按钮(8188)、云端 API 设置面板、LoRA 下拉点选、模型下拉中文分组、高级参数折叠区
- **云端 LLM 双后端**（不占显存）：
  - cloud = token-plan 包月（sk-sp-），引擎模型名 qwen3.8-max
  - dashscope = 百炼按量付费（sk-ws-），引擎模型名 qwen-plus
  - 兜底链 `[cloud, dashscope, t3, q14, t2]`（云端优先，本地兜底）
- **云端 VL 判分**：qwen-vl-plus/max（webui 可切换），判分 0-100（面/构图/画质/氛围 四维）
- **闭环自动出图 t_auto**（`auto_draft.yaml`）〔**11-04 整条退役**：它的驱动力是云端 VL 的 0-100 美学分——判"好不好"和选"交回哪一轮"都是机器在裁，用户裁「所有带美学判定的都交给人来判，机器只负责能实际判定的缺陷」⇒ 本体已删（`t_auto`/`vl_score_image`/`@task("vl_aesthetic")` 连函数体一起摘），`auto_draft.yaml` 原处是路障桩（`run.py auto_draft` 打印原因并以 78 退出）。替代：`image_draft_batch` 出草稿交人挑 → `image_refine` 按编号精修；事实在场核查走 `vl_qc`〕：LLM 生成提示词 → 出图 → VL 判分 → 低分改写重试（max_tries 轮）；rewrite_mode=text（VL 判分 + 文本 LLM 改写，省）/ vl（VL 看图直改，贵，失败自动回退 text）
- 密钥存储：`E:\密钥文件\webui_settings.json`（cloud/dashscope 双 profile 的 key/base_url/model/vl_model），严禁入工程目录
- 产物：`E:\FLUX_Workflow\out\<run_id>\{draft,final}\` 自包含批次夹
- 运行状态：`E:\LocalAI\logs\workflows\status.json`（QS 监控器/管理软件只读）

## 重要改动记录

### 2026-09-03 ｜ WebUI 网页操作台从零搭建（C 方案：先自用后交人）
- 摘要：新增 `webui.py`（http.server + 内嵌 HTML/JS，8787 端口，零新依赖）。定位 C：B 底线防呆（默认只露输入/按钮，高级参数折叠区，错误翻人话，绝不写回 YAML/产物，无删除能力）+ A 高级区（LoRA/尺寸/步数等 + 原始信息开关）。只读壳：子进程调 `python run.py <wf> --set k=v`，不 import run 避免耦合。插件口约定 status.json 稳定契约，QS 监控器后续作插件接入。入口：桌面快捷方式 / 双击 `E:\LocalAI\workflows\start-webui.bat`（纯 ASCII 编码，防中文路径 bat 静默失败）
- 影响范围：新增 `E:\LocalAI\workflows\webui.py`、`start-webui.bat`；网页 8787
- 决策/结论：LLM 默认关（webui 不主动拉起本地 LLM）；模型库目录显示真实路径 D:\Models\ComfyUI（D=优化主力盘，E=备份）

### 2026-09-03 ｜ 双云端后端接入（包月 + 按量）+ 密钥迁移
- 摘要：config.yaml 新增 remote 云端后端 cloud（token-plan 包月）与 dashscope（百炼按量）；fallback_chain 改 `[cloud, dashscope, t3, q14, t2]`。webui「云端 API 设置」面板：云端服务 profile 下拉（包月/按量）+ Base URL + 模型名下拉 + API Key + 测试连接；保存/测试/启动运行时按 profile 注入环境变量 `AW_CLOUD_API_KEY` / `AW_DASHSCOPE_API_KEY`。密钥从工程目录迁到 `E:\密钥文件\webui_settings.json`
- 相关文件：`config.yaml`、`webui.py`、`E:\密钥文件\webui_settings.json`
- 决策/结论：key 一律入 E:\密钥文件、走环境变量，不进代码库；API Key 显示只露尾 4 位

### 2026-09-03 ｜ 云端 VL 判分 + t_auto 闭环自动出图（agent 最小闭环）
- 摘要：tasks.py 新增 `vl_score_image()`（多模态四维判分，先压缩到 768px JPEG 再上传，防 12MB PNG 超限 400）；支持 `rewrite_prompt` 让 VL 同时输出改写提示词（new_prompt）。新增 `@task("auto") t_auto()`：循环 LLM→出图→VL 判分→低分改写（text 模式 = VL 判分 + 文本 LLM 改写；vl 模式 = VL 看图直改），VL 未返回 new_prompt 或异常时自动回退 text 模式；返回最优轮产物 + 分数轮次表。配套 `workflows/auto_draft.yaml`、`tests/test_auto_flow.py`（7 个测试）
- 相关文件：`tasks.py`、`workflows\auto_draft.yaml`、`tests\test_auto_flow.py`
- 实跑验收：2026-09-03 22:03 auto 6 轮成功（310s，每轮 85-88 分）——**注意**：全程 VL 判分正常但均「未返回 new_prompt」，实际改写全走 text 回退，vl 直改路径待排查

### 2026-09-03 ｜ WebUI 交互迭代（进度真实化 + 中文下拉 + LoRA/模型选择）
- 摘要：修复「历史批次一直显示批量出草稿」误判（区分运行中/空闲，空闲显示 ◻）；进度追踪改读真实运行的 status.json（不依赖下拉选择）；历史批次倒序最新在上；加 ComfyUI 原版编辑器按钮(8188)；模式/后端字段全部中文下拉；LoRA 改下拉点击添加 + 独立强度（自动检测 ComfyUI 已装 LoRA，默认不加）；主题框下加提示「LLM 润色关闭时提示词仅直传」
- 决策/结论：模型名下拉先放全部百炼模型（分类组）→ 实测图像/视频/3D/音频/向量模型不支持 chat completions（404）→ **收敛为仅文本生成类模型**（千问 qwen3.8-max/3.7-plus/3.8-flash/max/plus/turbo/long + 三方 deepseek-v4-pro/flash、kimi-k3、glm-5.2、GLM-5.3、MiniMax-M3、mimo-v2.5-pro + qwen-coder-plus）；VL 判分模型单独下拉（qwen-vl-max/vl-plus/qwen3.5-omni-plus），存 `vl_model` 字段、运行注入 `AW_VL_MODEL`

### 2026-09-03 ｜ Base URL /v1 拼接修复（曾全链 404）
- 摘要：tasks.py 请求 URL = `base_url + "/v1/chat/completions"`，但曾把 base_url 写成含 `/v1` 的 `.../compatible-mode/v1` → 拼出 `/v1/v1/chat/completions` → 404。修复：config.yaml、webui.py 默认 URL、webui_settings.json 三处**统一去掉末尾 /v1**（引擎拼 `{base}/v1/chat/completions`；webui 测试连接同规则）；曾连带把 DashScope 默认 base_url 填成不带 /v1，用户再报错后统一。修后 auto 实跑 6 轮成功
- 踩坑：base_url 一律**不带 /v1**；引擎与 webui 测试连接都是 `{base}/v1/chat/completions`

### 2026-09-03 ｜ 云端账号现状（双停摆，本地链不受影响）
- 摘要：实测诊断三个 ping——cloud 包月 HTTP 429 insufficient_quota（token-plan 周额度耗尽，重置约 09-06 02:07 北京时间）；dashscope 按量 qwen-plus 与 deepseek-v4-pro 均 HTTP 400 Arrearage「Access denied, account in good standing」（账号欠费/余额不足，非模型问题，需去费用中心充值或开通按量）。错误指向阿里云官方错误码 #overdue-payment
- 影响：云端 LLM 润色 + VL 判分暂不可用；自动模式会落到本地 t3/q14/t2 兜底
- 决策/结论：两个云端都用同一份额度判断，换模型无法绕过账号级欠费

### 2026-09-04 ｜ GitHub 仓库创建 + 推送 + 敏感信息审查
- 摘要：gh CLI v2.100.0 安装并 OAuth 认证（设备码流程），创建 ruoshui-xiaoxiang/auto-workflow 私有仓库，推送 26 文件 4138 行。推送前全量敏感信息审查：grep API key / token / password / secret / sk- / ghp_ 等模式，确认代码中仅引用环境变量名（AW_CLOUD_API_KEY 等），实际密钥均在 E:\密钥文件\，.gitignore 已排除密钥目录
- 相关文件：`E:\LocalAI\workflows\.gitignore`
- 踩坑：① gh auth 被 User 级 GITHUB_TOKEN（classic PAT ghp_）拦截——gh 忽略 classic PAT，需清 User 环境变量后重新 OAuth；Machine 级需管理员权限清除。② git push 走本地代理 127.0.0.1:7890（Clash）但代理未开→连接失败，用 `git -c http.proxy="" -c https.proxy="" push` 绕过
- 决策/结论：仓库暂为 private；后续公开前再过一遍 .gitignore

### 2026-09-04 ｜ Inno Setup 安装包编译（分发版 v0.1）
- 摘要：新增 `setup.iss`（Inno Setup 6 安装脚本），打包 webui.py/run.py/tasks.py/config.yaml/start-webui.bat/README.md + workflows/ + tools/ + tests/ + comfy/ + first-run/ 子目录。Python 嵌入式环境不打包，由 first-run 脚本首次运行时自动下载。编译输出 `installer_output\auto-workflow-setup.exe`（2.1MB）
- 相关文件：`E:\LocalAI\workflows\setup.iss`、`E:\LocalAI\workflows\installer_output\auto-workflow-setup.exe`
- 踩坑：① setup.iss 的 Source 路径相对于 .iss 文件自身位置，不能加 `workflows\` 前缀。② Inno Setup 6.7.3 不自带 ChineseSimplified.isl 语言文件，回退用 `english` + `Default.isl`。③ `LicenseFile=` 空行会导致编译报错，需删除整行。④ jrsoftware.org 下载页返回 HTML 而非 exe，实际安装包需从 GitHub Releases 获取

### 2026-09-04 ｜ SCP 部署到云服务器 + 网站可下载
- 摘要：通过 SCP（SSH 密钥认证）将安装包上传到云服务器 /opt/product-site/downloads/，nginx 反向代理映射 /downloads/ 路径，网站 www.huahuayoueryuan.com 可直接下载。连接信息：root@47.250.138.158，密钥 %USERPROFILE%\.ssh\server_deploy_key（RSA 2048，指纹 SHA256:cOdm5B/7bjqb6iicArdKmqv54DXDd2mm+b66ycsaaM4）
- 相关文件：`E:\密钥文件\云服务器连接信息.md`（连接详情）、`E:\6a8b0dd1b3ead574d77ceda3\_deploy_local.ps1`（部署脚本参考）
- 决策/结论：服务器走 SSH 密钥认证（非 FTP），部署路径 /opt/product-site/，downloads 子目录对外可下载

### 2026-09-04 18:52 ｜ 网页操作台启动器修复 + 引擎代理免疫 + 兜底链全路径实测
- 摘要：①用户报"桌面 auto-workflow 网页操作台 一键不弹网页"。根因：14:17 安装器测试残留的 webui 服务一直占着 8787，双击启动器时旧 bat 无脑起新实例（端口被占直接退出）+ 轮询 /health 探到的是旧实例 → 打印 ready 但没人开浏览器。start-webui.bat 重写为幂等两路：先探 /health，活着直接 `start` 开页复用；没跑才冷启动（webui.py 自带 webbrowser.open）。延时从 `timeout /t` 换 `ping -n`（Git Bash 环境下 GNU timeout 同名冲突）。两路径均实测通过。②当晚 t3 探活事故：18:46 兜底链测试中 t3 轮询 180s 全败，而 llama-server 拉起后 5s 即监听（进程创建时间实证），18:51 复现同样代码/环境完全正常——高度怀疑系统代理（Clash 注册表代理）当时劫持了 127.0.0.1 请求。加固：tasks.py 新建 `SESSION(trust_env=False)` 替换全部 5 处 requests 调用（本机服务永不走代理），http_ok 记录最后异常并进超时日志。③LLM 兜底链全路径实测通过：t1 冷启动 279s 自动拉起（09-02）、页缓存热重启 9s、坏后端名跳过→t3 接管、auto 链云端无 key 自动跳过落本地。
- 影响范围：`start-webui.bat`（重写）、`tasks.py`（SESSION 代理免疫 + 超时诊断信息）、桌面快捷方式行为恢复
- 决策/结论：本机回环请求永不走代理（trust_env=False 是框架级铁律）；诊断类临时脚本用完即删
- 未验证项：代理劫持根因是推断（事后无法复现），但加固本身无副作用；tasks.py 改动未提交 git（仓库由其他会话管理，setup.iss 也有未提交改动）

## 当前待办 / 阻塞

- [ ] **云端恢复**：包月等 09-06 02:07（北京时间）额度重置；按量去阿里云费用中心充值/开通后即恢复（当前 2026-09-03 阻塞云端润色与判分）
- [ ] vl 直改路径排查：VL 判分正常但不输出 new_prompt（text 回退兜底中），试 qwen-vl-max 或调 prompt 结构
- [ ] 后续：其他任务工作流、定时值守 schtasks、VLM 图像质检、QS 监控器作插件接入
- [ ] 后续：ZCode 注册为公共记忆消费方（README 读取指引表）
- [x] 云端 API 加入兜底链头部 + WebUI 设置面板 + 闭环自动出图（2026-09-03 已完成）

## 关键路径速查

| 内容 | 路径 |
|---|---|
| 引擎入口 | `E:\LocalAI\workflows\run.py` |
| 任务插件（llm/comfyui/files/shell/auto/vl 判分） | `E:\LocalAI\workflows\tasks.py` |
| 网页操作台（8787） | `E:\LocalAI\workflows\webui.py` + `start-webui.bat` |
| 后端注册与兜底链 | `D:\AIWorkflow\engine\config.yaml` 〔11-04 更正：原 `E:\LocalAI\workflows\config.yaml` 盘上已无〕 |
| 工作流定义 | `D:\AIWorkflow\engine\workflows\*.yaml` 〔11-04 更正；现役 34 条，`run.py --list` 可查〕 |
| ComfyUI API 模板 | `D:\AIWorkflow\engine\comfy\*.json` 〔11-04 更正；FLUX 线 10 份模板已退役，原处是路障桩〕 |
| 云端密钥（双 profile） | `E:\密钥文件\webui_settings.json`（库内不存密钥）〔文件在，但 8787 webui 已废 ⇒ 它不再是现役配置面〕 |
| VL key / base | `E:\密钥文件\阿里多模态.txt` 〔**盘上不存在** ⇒ `_vl_credentials()` 恒 None ⇒ 一切 `vl_*` 自动 disabled（不是"通过"，是未启用）。目录里只有 `阿里.txt`，其第 1 行是"按量付费"＋key **粘在一起**，而代码取 `lines[0]` 当 key、`lines[1]` 当 base_url ⇒ 要启用得先把 key 单独放对位置，别指望改个文件名就行〕 |
| 运行日志 / 状态 | `D:\AIWorkflow\logs\workflows\`（status.json 供监控读）〔11-04 更正〕 |
| 产物（自包含批次夹） | `E:\图像影音资源池\<项目>\批次\<run_id>\` 〔11-04 更正：原 `E:\FLUX_Workflow\out\` 盘上已无；现役由 `pool_root\project\batch_subdir` 派生，`--tier play` 才落 ComfyUI 的娱乐流预览区〕 |
| 测试 | `E:\LocalAI\workflows\tests\test_auto_flow.py` |
| Inno Setup 安装脚本 | `E:\LocalAI\workflows\setup.iss` |
| 安装包产物 | `E:\LocalAI\workflows\installer_output\auto-workflow-setup.exe` |
| GitHub 仓库 | `ruoshui-xiaoxiang/auto-workflow`（private） |
| 云服务器连接信息 | `E:\密钥文件\云服务器连接信息.md` |
| 服务器部署脚本参考 | `E:\6a8b0dd1b3ead574d77ceda3\_deploy_local.ps1` |

## 注意事项 / 踩坑提醒

- **云端 base_url 不带 /v1**，引擎与 webui 测试连接统一拼 `{base}/v1/chat/completions`（拼重会 404）
- **只有文本生成类模型支持 chat completions**；图像/视频/3D/音频/向量等生成模型走不同协议，不能进 LLM 模型下拉
- webui 里选的模型名主要用于测试连接；**实际跑工作流用的引擎模型名是 config.yaml `models.<backend>.name`**（cloud=qwen3.8-max / dashscope=qwen-plus），两者别混淆
- 工作流 YAML 步骤级参数要支持 `--set` 覆盖，必须写 `{{args.xxx}}`
- LLM 步骤与生图步骤同链时 LLM 排前（生图按显存仲裁杀 llama-server 端口 11434/11435/11436/1234）
- bat 含中文路径必须纯 ASCII 编码（UTF-8 无 BOM 会被 cmd 按 GBK 解析静默失败）
- 密钥一律 E:\密钥文件，走环境变量注入（AW_CLOUD_API_KEY / AW_DASHSCOPE_API_KEY / AW_VL_MODEL / AW_VL_API_KEY），不入库不落盘工程
- 路径全 ASCII（命名铁律）
- **git push 代理绕过**：本地配了 http.proxy=http://127.0.0.1:7890（Clash），代理未开时 push 失败，用 `git -c http.proxy="" -c https.proxy="" push` 临时绕过
- **GITHUB_TOKEN 与 gh auth 冲突**：User/Machine 级的 classic PAT（ghp_）会被 gh 识别但忽略（gh 只支持 fine-grained PAT 或 OAuth），导致 auth 失败。需清 User 级环境变量后重新 `gh auth login`；Machine 级需管理员权限
- **Inno Setup 语言文件**：6.7.3 不自带 ChineseSimplified.isl，用 `Name: "english"; MessagesFile: "compiler:Default.isl"` 回退；`LicenseFile=` 空行会报错需删除
- **setup.iss Source 路径**：相对于 .iss 文件自身位置（即 workflows 根目录），不要加 `workflows\` 前缀
- **服务器部署走 SSH/SCP**（非 FTP），密钥认证 `%USERPROFILE%\.ssh\server_deploy_key`，详见 `E:\密钥文件\云服务器连接信息.md`
