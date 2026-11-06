这个文件夹是给「本地脚本化出片流水线 · 娱乐通道」用的。
子目录 API格式_非画布 里那 6 份是引擎提交给 ComfyUI 的原始节点图（API 格式，带 __REF1__/__PROMPT__ 占位符），不是画布，直接双击打开多半是空的或报错——它们是排障用的：想知道某条流到底把哪张图接到了哪个节点、首帧/尾帧怎么接，看这里。
要真正的可视化画布，请照上一级目录里 H3_首帧视频_T8_完整工作流.json 那种格式（UI 格式，带 nodes/links）另存一份，参数就能在网页里手改。
六份对应关系：fl2va_api=锁首帧；fl2va_dual_api=锁首尾帧；fl2va_nolora_api=锁首帧·20步不挂LoRA；fl2va_dual_nolora_api=两头夹·20步不挂LoRA；fl2va_dual_lora=打斗档(双LoRA)；ref2va_api=多参考图四图。
