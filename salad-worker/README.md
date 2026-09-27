# Salad GPU Worker

This project uses per-run priority routing.

Salad priority is configured per Container Group, so the controller uses
one queue + one scale-to-zero group per priority tier:

- high: qwen-comfyui-high / qwen-comfyui-fp8-high
- medium: qwen-comfyui-medium / qwen-comfyui-fp8-medium
- low: qwen-comfyui-low / qwen-comfyui-fp8-low
- batch: qwen-comfyui-batch / qwen-comfyui-fp8-batch

Default priority: medium.

Deploy Medium first:

```bash
bash scripts/salad-deploy.sh --priority medium
bash scripts/salad-deploy.sh --apply --priority medium
```

Deploy all tiers:

```bash
bash scripts/salad-deploy.sh --apply
```

The deploy script verifies that the resulting group exposes both
queue_connection and queue_autoscaler in the live API response.
