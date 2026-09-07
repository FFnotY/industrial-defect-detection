"""模型适配层入口。

后端只通过本模块暴露的两个函数与模型打交道，
从而保证"换模型不用改后端"。
"""

from model.inference import load_model, run_inference

__all__ = ["load_model", "run_inference"]
