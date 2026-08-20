"""Minimal Hugging Face adapter. Requires transformers + torch for real runs."""
import time

def load_model(model_name):
    from transformers import AutoTokenizer, AutoModelForCausalLM
    import torch
    tok=AutoTokenizer.from_pretrained(model_name)
    model=AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", device_map="auto")
    model.eval()
    return tok, model

def generate(tok, model, prompt, max_new_tokens=128):
    import torch
    inputs=tok(prompt, return_tensors="pt").to(model.device)
    t0=time.perf_counter()
    with torch.no_grad():
        out=model.generate(**inputs,max_new_tokens=max_new_tokens,do_sample=False)
    dt=time.perf_counter()-t0
    text=tok.decode(out[0][inputs['input_ids'].shape[1]:],skip_special_tokens=True)
    return text, dt
