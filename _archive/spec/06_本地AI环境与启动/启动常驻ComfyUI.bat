@echo off
cd /d D:\AIWorkflow\ComfyUI_H3
python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --use-sage-attention --reserve-vram 2.0 --port 8189 --output-directory D:\AIWorkflow\ComfyUI_H3\output
