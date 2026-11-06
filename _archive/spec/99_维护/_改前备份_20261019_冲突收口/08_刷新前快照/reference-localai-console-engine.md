
### ⚠️ 别用 `check_preflight.py` 的 CLI 自审 H3 I2VA 提示词（2026-09-24 踩到，会假报错）

`py tools/check_preflight.py --prompt-file X --only G7` **没有 `--prompt-kind` 参数**，`spec["prompt_kind"]` 取不到就默认 `"video"`，于是 G7 走的是**中文十块**分支（要"主体与关系/事件脚本/保持一致/镜头/声音"），对**官方 H3 I2VA 三字段英文格式**必然报 `✗ 缺核心分块`。引擎侧不会误报，因为工作流 YAML 的 `pre` 步显式写了 `prompt_kind: h3_i2va` 注入 spec。

**反证法（下次照做）**：拿一份**引擎已经放行并渲出来过**的提示词用同样 CLI 跑——它也报同样的错，就说明是调用方式错、不是提示词错。别据此改提示词。

**正确的离线自审**：直接 import 真模块调函数，自己传 kind——
`cp.run_checks({"prompt": txt, "refs": [], "prompt_kind": "h3_i2va", "only": ["G7"], "provider": "local"}, cp.Report())`
（`Report.errors` 元素可能是 tuple，取 `x[1]`。）
