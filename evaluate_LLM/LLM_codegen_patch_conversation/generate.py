import argparse
import os

# os.environ['AZURE_OPENAI_ENDPOINT'] = 'https://dbswjdec30.openai.azure.com/openai/deployments/xms2/chat/completions?api-version=2023-07-01-preview'
# os.environ['AZURE_OPENAI_KEY'] = '02c4d96767bb47679bcfd24c97daa3eb'
# os.environ['AZURE_OPENAI_BASE'] = 'https://dbswjdec30.openai.azure.com'

from os import PathLike
from codegen.model import DecoderBase, make_model
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

import openai
import  traceback
import json 
import random 
def read_dataset(dataset_path):
    if dataset_path.endswith(".jsonl"):
        with open(dataset_path) as f :
            data = [json.loads(x) for x in f.readlines() ]
            return data 
    else:
        try :
            with open(dataset_path) as f :
                data = json.load(f)
        except :
            with open(dataset_path) as f :
                data = [json.loads(x) for x in f.readlines() ]

    

def code_generate(args, workdir: PathLike, model: DecoderBase, dataset_path):
    dataset_name = os.path.basename(dataset_path)
    with Progress(
        TextColumn(
            f"{dataset_name} •" + "[progress.percentage]{task.percentage:>3.0f}%"
        ),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
    ) as p:
        assert os.path.isfile(dataset_path), dataset_path 
        dataset = read_dataset(dataset_path) 
        # dataset = dataset[:4]

        p_name = os.path.basename(  os.path.dirname(dataset_path) ) 
        for  item  in p.track(dataset ):
            # print ( type(item) , "item .", list(item ) )
            task_id, task  = item ["idx"], item #["prompt"]
            
            os.makedirs(os.path.join(workdir, p_name), exist_ok=True)
            log = f"Codegen: {p_name} @ {model}"
            n_existing = 0
            if args.resume:
                # count existing .py files
                n_existing = len(
                    [
                        f
                        for f in os.listdir(os.path.join(workdir, p_name))
                        if  task_id in f 
                    ]
                )
                if n_existing > 0:
                    log += f" (resuming from {n_existing})"

            nsamples = args.n_samples - n_existing

            sidx = args.n_samples - nsamples
            try:
                while sidx < args.n_samples:
                    outputs = model.codegen(
                        task["prompt"], 
                        do_sample=not args.greedy,
                        num_samples=args.n_samples - sidx,
                    )
                    p.console.print("=====>"*8, sidx)
                    p.console.print(outputs)
                    assert outputs, "No outputs from model!"
                    for impl in outputs:
                        rnd = random.randint(0, 1000)
                        try:
                            with open(
                                os.path.join(workdir, p_name, f"{task_id}@{rnd}@{sidx}"),
                                "w",
                                encoding="utf-8",
                            ) as f:
                                if model.conversational:
                                    f.write(impl)
                                else:
                                    f.write(task["prompt"] + impl)
                        except UnicodeEncodeError:
                            traceback.print_exc() 
                            continue
                        sidx += 1
            except openai.APIError:
                traceback.print_exc()
                pass 

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=str)
    parser.add_argument("--bs", default=1, type=int)
    parser.add_argument("--temperature", default=0.0, type=float)
    parser.add_argument(
        "--dataset-path", required=True, type=str, 
    )
    parser.add_argument("--root", type=str, required=True)
    parser.add_argument("--n_samples", default=1, type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--greedy", action="store_true")
    # id_range is list
    args = parser.parse_args()

    if args.greedy and (args.temperature != 0 or args.bs != 1 or args.n_samples != 1):
        args.temperature = 0
        args.bs = 1
        args.n_samples = 1
        print("Greedy decoding ON (--greedy): setting bs=1, n_samples=1, temperature=0")

    # Make project dir
    os.makedirs(args.root, exist_ok=True)
    # Make dataset dir
    # os.makedirs(os.path.join(args.root, args.dataset), exist_ok=True)
    # Make dir for codes generated by each model

    args.model = args.model.lower()

    model = make_model(
        name=args.model, batch_size=args.bs, temperature=args.temperature
    )

    workdir = os.path.join(
        args.root,
        # args.dataset,
        args.model
        + f"_temp_{args.temperature}"
        # + ("" if args.contract_type == "none" else f"-contract-{args.contract_type}"),
    )

    os.makedirs(workdir, exist_ok=True)

    with open(os.path.join(workdir, "args.txt"), "w") as f:
        f.write(str(args))

    code_generate(args, workdir=workdir, model=model, dataset_path=args.dataset_path)


if __name__ == "__main__":
    '''
    export AZURE_OPENAI_ENDPOINT=xx 
    export AZURE_OPENAI_KEY=xx
    export AZURE_OPENAI_BASE=xx
    python generate.py --model  --root 
    '''
    main()

