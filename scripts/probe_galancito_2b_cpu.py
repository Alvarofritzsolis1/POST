#!/usr/bin/env python3
"""Root feasibility gate: real CPU training on Qwen 3.5 2B, never production.

Only the final MLP down projection receives a LoRA adapter. The entire frozen
prefix runs without autograd, avoiding backwards through quantized recurrent
layers. This deliberately limited experiment does not certify general learning.
"""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from time import monotonic, time
from uuid import uuid4
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "backend"))
from app.galancito_model_config import QWEN_TRAINING_MODEL as MODEL
from galant_cpu_lora_resources import snapshot, should_pause

PROFILE = "last-down-proj-fp32-v1"
REVISION = "15852e8c16360a2fea060d615a32b45270f8a8fc"
SYSTEM = "Orienta a contratistas chilenos con lenguaje sencillo. No inventes datos."
EXAMPLES = (
    ("Ola busco peguita", "Hola, ¿qué oficio tienes?"),
    ("No cacho qué es cuadrilla", "Es un grupo de personas que trabajan juntas."),
    ("Somos tres maestros", "Entendido, son tres maestros. ¿Qué trabajos realizan?"),
    ("Y las lucas cuanto son", "El equipo debe confirmar el monto."),
    ("Puedo partir altiro", "Anotado, tienes disponibilidad inmediata."),
    ("No tengo correo", "Puedes seguir conversando por aquí."),
    ("Ya te dije que soy carpintero", "Tienes razón. ¿Trabajas solo o con un equipo?"),
    ("No entiendo el formulario", "Te ayudo por acá, una pregunta a la vez."),
    ("Hago pintura hace ocho años", "Anotado, ocho años de experiencia en pintura."),
    ("Me puede atender una persona", "Podemos solicitar ayuda al equipo.")
)
HOLDOUT = (
    ("Ando sin trabajo hace rato", "Cuéntame qué oficio tienes."),
    ("Qué significa a trato", "Es un trabajo pagado según las condiciones acordadas."),
    ("No tengo gente voy yo nomas", "Entendido, trabajas solo."),
    ("Me dijeron que pagan el viernes", "No puedo confirmar esa fecha.")
)

def snapshot_revision(path, expected=None):
    path = Path(path)
    rev = path.parent.name
    if (path.name != "config.json" or path.parent.parent.name != "snapshots"
            or path.parent.parent.parent.name != "models--" + MODEL.replace("/", "--")
            or not re.fullmatch(r"[0-9a-f]{40}",rev)
            or (expected is not None and rev != expected)):
        raise RuntimeError("Cannot prove exact base-model revision")
    return rev

def select_target(names):
    layers = []
    targets = []
    for name in names:
        m = re.search(r"(?:^|\.)layers\.(\d+)$",name)
        if m:
            layers.append(int(m.group(1)))
        m = re.search(r"(?:^|\.)layers\.(\d+)\.mlp\.down_proj$",name)
        if m:
            targets.append((int(m.group(1)),name))
    if not layers or not targets or len([t for t in targets if t[0]==max(layers)])!=1:
        raise RuntimeError("Final dense MLP projection not uniquely identified")
    return next(name for index,name in targets if index==max(layers))

def blockers(measured):
    required = {"host_free_mb":6000,"cgroup_limit_mb":4800,
                "cgroup_available_mb":4300,"disk_free_mb":7000}
    return [key for key,minimum in required.items()
            if type(measured.get(key)) not in (int,float)
            or not math.isfinite(measured[key]) or measured[key]<minimum]

def write_report(path,report):
    temporary = path.with_name("." + path.name + "." + uuid4().hex)
    try:
        with temporary.open("x",encoding="utf-8") as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--allow-download",action="store_true")
    parser.add_argument("--steps",type=int,choices=range(1,11),default=10)
    parser.add_argument("--threads",type=int,choices=(2,4),default=2)
    parser.add_argument("--stop-after",type=int,choices=range(1,11))
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--conversation-eval",action="store_true")
    parser.add_argument("--control-file",type=Path)
    parser.add_argument("--org")
    parser.add_argument("--generation",type=int)
    parser.add_argument("--approved-dir",type=Path)
    parser.add_argument("--expected-dataset-sha256")
    parser.add_argument("--output",type=Path,default=Path("/private/2b-probe"))
    args=parser.parse_args()
    if args.control_file and (not args.org or not args.generation):
        parser.error("Control file requires organization and generation")
    def control_guard():
        if args.control_file:
            from app.max_power_2b_control import authorized,read
            if not authorized(read(args.control_file),args.org,args.generation):
                raise InterruptedError("MAX POWER paused or session expired")
    if bool(args.approved_dir)!=bool(args.expected_dataset_sha256) or (args.approved_dir and not args.conversation_eval):
        parser.error("Approved training requires signed dataset digest and reserved evaluation")
    root=args.output
    root.mkdir(parents=True,exist_ok=True)
    path=root/"latest.json"
    resume_path=root/"resume.json"
    measured=snapshot(root)
    reasons=blockers(measured)
    report={"model":MODEL,"profile":PROFILE,"status":"blocked" if reasons else "preflight_passed",
            "timestamp":time(),"preflight":measured,"blockers":reasons,"steps":[],
            "adapter_changed":False,"production_verified":False,"quality_improvement_verified":False,
            "data_kind":"curated_synthetic"}
    write_report(path,report)
    if reasons or not args.run:
        return 2 if reasons else 0
    try:
        control_guard()
        bundle=None
        if args.approved_dir:
            from galancito_2b_approved import approved_bundle,select_groups
            bundle=approved_bundle(args.approved_dir,os.environ.get("GALANT_DATASET_APPROVAL_PUBLIC_KEY",""))
            if bundle["dataset_digest"]!=args.expected_dataset_sha256:
                raise RuntimeError("Approved dataset changed before training")
            report.update(data_kind="human_reviewed_real",approved_dataset_sha256=bundle["dataset_digest"])
            write_report(path,report)
        import torch
        import bitsandbytes as bnb
        import transformers, peft
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer,Qwen3_5ForCausalLM,BitsAndBytesConfig
        from peft import LoraConfig,get_peft_model
        from peft.utils.save_and_load import load_peft_weights,set_peft_model_state_dict
        torch.set_num_threads(min(args.threads,os.cpu_count() or 1))
        torch.set_num_interop_threads(1)
        torch.manual_seed(42)
        report["software"]={"torch":torch.__version__,"bitsandbytes":bnb.__version__,
                            "transformers":transformers.__version__,"peft":peft.__version__}
        report["threads"]=torch.get_num_threads()
        report["status"]="loading"
        write_report(path,report)
        t=monotonic()
        options={"trust_remote_code":False,"local_files_only":not args.allow_download,
                 "revision":REVISION,"token":False}
        config_path=hf_hub_download(repo_id=MODEL,filename="config.json",
                                    revision=REVISION,local_files_only=options["local_files_only"],token=False)
        report["base_revision"]=snapshot_revision(config_path,REVISION)
        tokenizer=AutoTokenizer.from_pretrained(MODEL,**options)
        # The recurrent gates have 16 outputs, below the 32-output CPU packing
        # block. Keep those in BF16 and quantize the other linear layers once.
        # Nested quantization spawns native workers outside the CPU thread limit.
        model,loading=Qwen3_5ForCausalLM.from_pretrained(MODEL,dtype=torch.bfloat16,
            device_map={"":"cpu"},low_cpu_mem_usage=True,attn_implementation="eager",
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=False,bnb_4bit_compute_dtype=torch.float32,
                llm_int8_skip_modules=["lm_head", "in_proj_a", "in_proj_b"]),
            output_loading_info=True,**options)
        if any(k.startswith(("model.","lm_head")) for k in loading.get("missing_keys",())):
            raise RuntimeError("Missing text weights")
        quantized=sum(isinstance(m,bnb.nn.Linear4bit) for m in model.modules())
        if not quantized or not getattr(model,"is_loaded_in_4bit",False):
            raise RuntimeError("No verified 4-bit layers")
        report.update(quantized_layers=quantized,load_seconds=round(monotonic()-t,3))
        def guard(check_control=True):
            if check_control:
                control_guard()
            memory=snapshot(root)
            if should_pause(memory):
                raise RuntimeError("Memory reserve below safe limit")
            return memory
        guard()
        # No generic k-bit preparation: that expands frozen tensors to FP32
        # and enables input gradients. Only the adapter is FP32 trainable.
        model.config.use_cache=False
        model.gradient_checkpointing_disable()
        for param in model.parameters():
            param.requires_grad_(False)
        target=select_target(name for name,_ in model.named_modules())
        report["target_module"]=target
        if not isinstance(model.get_submodule(target),bnb.nn.Linear4bit):
            raise RuntimeError("Final target is not the verified quantized projection")
        if not isinstance(model.get_output_embeddings(),torch.nn.Linear) or isinstance(model.get_output_embeddings(),bnb.nn.Linear4bit):
            raise RuntimeError("Output head must be native torch linear")
        model=get_peft_model(model,LoraConfig(r=4,lora_alpha=8,lora_dropout=0,
            target_modules=[target],task_type="CAUSAL_LM",bias="none"))
        named=[(name,param) for name,param in model.named_parameters() if param.requires_grad]
        if not named or any("lora_" not in n or target not in n or p.dtype!=torch.float32 for n,p in named):
            raise RuntimeError("Unexpected trainable parameters")
        params=[p for _,p in named]
        report["trainable_parameters"]=sum(p.numel() for p in params)
        def assert_frozen_input(module, inputs):
            if not inputs or not isinstance(inputs[0],torch.Tensor) or inputs[0].requires_grad:
                raise RuntimeError("Frozen prefix unexpectedly participates in backward")
        model.get_base_model().get_submodule(target).register_forward_pre_hook(assert_frozen_input)
        def digest():
            h=hashlib.sha256()
            for name,param in named:
                h.update(name.encode())
                h.update(param.detach().float().contiguous().cpu().numpy().tobytes())
            return h.hexdigest()
        initial=digest()
        optimizer=torch.optim.AdamW(params,lr=7e-5)
        def encode(question,answer):
            prefix=tokenizer.apply_chat_template([{"role":"system","content":SYSTEM},
                        {"role":"user","content":question}],tokenize=False,
                        add_generation_prompt=True,enable_thinking=False)
            a=tokenizer(prefix,add_special_tokens=False)["input_ids"]
            b=tokenizer(answer,add_special_tokens=False)["input_ids"]+[tokenizer.eos_token_id]
            if not b or len(a)+len(b)>192:
                raise RuntimeError("Diagnostic example exceeds token budget")
            return torch.tensor([a+b],dtype=torch.long),torch.tensor([[-100]*len(a)+b],dtype=torch.long)
        examples=EXAMPLES
        holdout=HOLDOUT
        reserved_real=[]
        if bundle:
            def short(rows):
                for row in rows:
                    try:
                        encode(row["messages"][0]["content"],row["messages"][1]["content"])
                    except RuntimeError:
                        continue
                    yield row
            train_rows=select_groups(short(bundle["samples"]["train"]),args.steps)
            reserved_real=select_groups(short(bundle["samples"]["test"]),10)
            examples=tuple((r["messages"][0]["content"],r["messages"][1]["content"]) for r in train_rows)
            holdout=tuple((r["messages"][0]["content"],r["messages"][1]["content"]) for r in reserved_real)
        dataset=hashlib.sha256(json.dumps([SYSTEM,examples,holdout,PROFILE,args.steps,
                    bundle["dataset_digest"] if bundle else None],ensure_ascii=False).encode()).hexdigest()
        report["dataset_sha256"]=dataset
        def reserved_loss():
            model.eval()
            values=[]
            with torch.no_grad():
                for q,a in holdout:
                    guard()
                    ids,labels=encode(q,a)
                    loss=model(input_ids=ids,labels=labels,use_cache=False).loss
                    if not torch.isfinite(loss):
                        raise RuntimeError("Non-finite reserved loss")
                    values.append(float(loss))
            return sum(values)/len(values)
        start=0
        if args.resume:
            saved=json.loads(resume_path.read_text())
            name,step=saved["candidate_id"],saved["step"]
            if (not re.fullmatch(r"candidate-[0-9a-f]{32}",name) or type(step) is not int
                    or not 1<=step<=args.steps or saved["revision"]!=REVISION
                    or saved["dataset"]!=dataset or saved["profile"]!=PROFILE
                    or saved["target"]!=target):
                raise RuntimeError("Incompatible checkpoint")
            folder=root/name
            checkpoint=folder/("step-"+str(step))
            if not checkpoint.resolve().is_relative_to(root.resolve()):
                raise RuntimeError("Checkpoint outside private root")
            for filename in ("adapter_model.safetensors","adapter_config.json","optimizer.pt"):
                f=checkpoint/filename
                if f.is_symlink() or file_hash(f)!=saved["files"][filename]:
                    raise RuntimeError("Checkpoint integrity mismatch")
            set_peft_model_state_dict(model,load_peft_weights(str(checkpoint),device="cpu"))
            if digest()!=saved["adapter_sha256"]:
                raise RuntimeError("Restored adapter hash mismatch")
            optimizer.load_state_dict(torch.load(checkpoint/"optimizer.pt",map_location="cpu",weights_only=True))
            if any(int(optimizer.state[p]["step"].item())!=step for p in params):
                raise RuntimeError("Optimizer step was not restored")
            start=step
            initial=saved["initial_sha256"]
            report.update(steps=saved["steps"],holdout_loss_before=saved["baseline"],
                          restored_adapter_sha256=digest(),restored_optimizer_step=step,
                          saved_adapter_step=step,latest_adapter_sha256=digest(),
                          adapter_changed=digest()!=initial)
        else:
            folder=root/("candidate-"+uuid4().hex)
            folder.mkdir()
            report["status"]="baseline_evaluation"
            write_report(path,report)
            report["holdout_loss_before"]=reserved_loss()
        report.update(candidate_id=folder.name,initial_adapter_sha256=initial,resumed_from_step=start)
        write_report(path,report)
        model.train()
        stop=min(args.steps,args.stop_after or args.steps)
        for step in range(start+1,stop+1):
            guard()
            ids,labels=encode(*examples[step-1])
            report.update(status="backward_pending",active_step=step)
            write_report(path,report)
            t=monotonic()
            optimizer.zero_grad(set_to_none=True)
            loss=model(input_ids=ids,labels=labels,use_cache=False).loss
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite training loss")
            loss.backward()
            missing=[n for n,p in named if p.grad is None]
            nonfinite=[n for n,p in named if p.grad is not None and not torch.isfinite(p.grad).all().item()]
            report["gradient_diagnostic"]={"missing":missing,"nonfinite":nonfinite}
            if missing or nonfinite:
                raise RuntimeError("Invalid adapter gradients; see named gradient diagnostics")
            if not any(torch.count_nonzero(p.grad).item() for p in params):
                raise RuntimeError("All adapter gradients are zero")
            norm=torch.nn.utils.clip_grad_norm_(params,1.0,error_if_nonfinite=True)
            before=digest()
            optimizer.step()
            after=digest()
            if after==before or not all(torch.isfinite(p).all().item() for p in params):
                raise RuntimeError("Optimizer did not produce a finite changed adapter")
            point={"step":step,"seconds":round(monotonic()-t,4),"loss":float(loss.detach()),
                   "grad_norm":float(norm),"adapter_changed":True,"adapter_sha256":after,"memory":snapshot(root)}
            report["steps"].append(point)
            checkpoint=folder/("step-"+str(step))
            temporary=folder/(".step-"+str(step)+"-"+uuid4().hex)
            model.save_pretrained(temporary,safe_serialization=True)
            torch.save(optimizer.state_dict(),temporary/"optimizer.pt")
            files={name:file_hash(temporary/name) for name in
                   ("adapter_model.safetensors","adapter_config.json","optimizer.pt")}
            if checkpoint.exists():
                checkpoint.rename(folder/("orphan-"+uuid4().hex))
            temporary.rename(checkpoint)
            write_report(resume_path,{"candidate_id":folder.name,"step":step,"revision":REVISION,
                "dataset":dataset,"profile":PROFILE,"target":target,"files":files,
                "initial_sha256":initial,"adapter_sha256":after,"steps":report["steps"],
                "baseline":report["holdout_loss_before"]})
            report.update(status="running",saved_adapter_step=step,latest_adapter_sha256=after,
                          adapter_changed=after!=initial)
            write_report(path,report)
            guard()
        if stop<args.steps:
            report["status"]="paused_after_verified_step"
        else:
            report["status"]="reserved_evaluation"
            write_report(path,report)
            report["holdout_loss_after"]=reserved_loss()
            with model.disable_adapter():
                report["restored_baseline_loss"]=reserved_loss()
            report["baseline_restored"]=math.isclose(report["restored_baseline_loss"],
                report["holdout_loss_before"],rel_tol=1e-5,abs_tol=1e-5)
            if not report["baseline_restored"] or not report["adapter_changed"]:
                raise RuntimeError("Baseline restoration or weight change not verified")
            if args.conversation_eval:
                from galancito_2b_conversation_gate import evaluate,compare
                def generate(history):
                    guard()
                    messages=[{"role":"system","content":SYSTEM}]+history
                    prompt=tokenizer.apply_chat_template(messages,tokenize=False,
                                add_generation_prompt=True,enable_thinking=False)
                    ids=tokenizer(prompt,add_special_tokens=False,return_tensors="pt")["input_ids"]
                    if ids.shape[1]>384:
                        raise RuntimeError("Reserved conversation exceeds context budget")
                    with torch.no_grad():
                        output=model.generate(input_ids=ids,attention_mask=torch.ones_like(ids),
                            max_new_tokens=40,do_sample=False,use_cache=True,
                            pad_token_id=tokenizer.eos_token_id)
                    return tokenizer.decode(output[0,ids.shape[1]:],skip_special_tokens=True).strip()
                model.eval()
                def evaluate_real():
                    from app.galancito_finetune_dataset import verified_match
                    from galancito_2b_conversation_gate import safety
                    rows=[]
                    for row in reserved_real:
                        answer=generate([row["messages"][0]])
                        safe=safety(answer)
                        rows.append({"passed":safe and verified_match(answer,row["reference_answer"],row["verifier"]),
                                     "safe":safe})
                    return rows
                with model.disable_adapter():
                    base_conversations=evaluate(generate)
                    base_real=evaluate_real() if reserved_real else []
                candidate_conversations=evaluate(generate)
                report["conversation_validation"]=compare(base_conversations,candidate_conversations)
                if reserved_real:
                    candidate_real=evaluate_real()
                    gains=sum(not x["passed"] and y["passed"] for x,y in zip(base_real,candidate_real))
                    regressions=sum(x["passed"] and not y["passed"] for x,y in zip(base_real,candidate_real))
                    report["approved_reserved_validation"]={"cases":len(reserved_real),
                        "baseline_passes":sum(x["passed"] for x in base_real),
                        "candidate_passes":sum(x["passed"] for x in candidate_real),
                        "regressions":regressions,
                        "safety_regressions":sum(x["safe"] and not y["safe"] for x,y in zip(base_real,candidate_real)),
                        "gate_pass":gains>0 and regressions==0 and all(y["safe"] for y in candidate_real)}
                # Even a passing limited gate is not proof of production quality.
                # No activation on a production route; these are limited synthetic checks.
                report["quality_improvement_verified"]=False
            report["status"]="completed"
    except InterruptedError:
        report["status"]="paused"
    except Exception as exc:
        report.update(status="failed",error_type=type(exc).__name__,error=str(exc)[:400])
    write_report(path,report)
    print(json.dumps(report,ensure_ascii=False,allow_nan=False),flush=True)
    return 0 if report["status"] in {"completed","paused_after_verified_step"} else 1

if __name__=="__main__":
    raise SystemExit(main())
