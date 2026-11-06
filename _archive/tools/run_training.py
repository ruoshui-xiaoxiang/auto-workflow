import sys
import os

# Set HuggingFace mirror for China
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

# Workaround: Flash SDPA is unreliable on Blackwell (sm_120).
# cuDNN and memory-efficient SDPA were measured to complete forward and backward passes on this GPU.
import torch
torch.backends.cuda.enable_flash_sdp(False)
torch.backends.cuda.enable_mem_efficient_sdp(True)
torch.backends.cuda.enable_cudnn_sdp(True)
torch.backends.cuda.enable_math_sdp(True)
print(
    "SDPA backends: "
    f"flash={torch.backends.cuda.flash_sdp_enabled()}, "
    f"mem_efficient={torch.backends.cuda.mem_efficient_sdp_enabled()}, "
    f"cudnn={torch.backends.cuda.cudnn_sdp_enabled()}, "
    f"math={torch.backends.cuda.math_sdp_enabled()}",
    flush=True,
)

sys.path.insert(0, r'D:\AIWorkflow\training\toolkits\sd-scripts')
os.chdir(r'D:\AIWorkflow\training\toolkits\sd-scripts')

sys.argv = [
    'flux_train_network.py',
    '--config_file', r'D:\AIWorkflow\training\configs\asian_face_lora.toml',
    '--tokenizer_cache_dir', r'D:\AIWorkflow\training\tokenizers',
]

import runpy
runpy.run_path('flux_train_network.py', run_name='__main__')
