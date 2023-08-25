
import argparse
import pdb

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import numpy as np
import torch
from bottle import Bottle, request, response, run, static_file



def process_evidence_extraction_with_fixfactuality(dp):
    PROMPT_STR = "For the given document and claim sentence, find all document sentences providing evidence for claim, and then revise the claim to remove or replace unsupported facts."
    input_string = f"{PROMPT_STR} DOCUMENT:"
    for _i,sent in enumerate(dp["input_lines"]):
        input_string = f"{input_string} SENT{_i} {sent}"
    input_string = f"{input_string} CLAIM: {dp['before_summary_sent']}"

    output_string = f"EVIDENCE:"
    for ev_idx in dp["evidence_labels"]:
        output_string = f"{output_string} SENT{ev_idx}"
    output_string = f"{output_string} REVISION: {dp['after_summary_sent']}"

    dp["input_string"] = input_string
    dp["output_string"] = output_string

    return dp

TASK_TO_DSCREATE = {
    "evidence_extraction_with_fixfactuality": process_evidence_extraction_with_fixfactuality
}


def predict_generation(dp, model: AutoModelForSeq2SeqLM, tokenizer, nbeams, max_input_len, max_decode_len):
    inputs = tokenizer(dp["input_string"], return_tensors="pt", truncation=True, max_length=max_input_len)
    input_ids = inputs.input_ids.cuda()

    gen_output = model.generate(inputs=input_ids,
                                return_dict_in_generate=True,
                                decoder_input_ids=None,
                                output_scores=False,
                                max_length=max_decode_len,
                                num_beams=nbeams)

    gen_tokids = gen_output["sequences"][0]

    gen_tokids = gen_tokids[1:] # first token is pad
    if gen_tokids[-1].item()==tokenizer.eos_token_id:
        gen_tokids = gen_tokids[:-1]

    gen_string = tokenizer.decode(gen_tokids)
    print(gen_string)
    dp["prediction"] = gen_string



if __name__=="__main__":

    np.random.seed(1337)

    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=str, required=True)
    parser.add_argument("--port", type=int, default=1)
    parser.add_argument("--max-input-len", type=int, default=5000)
    parser.add_argument("--max-decode-len", type=int, default=150)

    args = parser.parse_args()

    model_path = args.model_path
    port = args.port
    max_input_len = args.max_input_len
    max_decode_len = args.max_decode_len

    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        use_fast=False
    )

    if tokenizer.pad_token==None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForSeq2SeqLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16
    ).cuda()

    # good for making generation fast
    model.config.use_cache=True

    model.gradient_checkpointing_disable()

    # test run
    predict_generation({"input_string":"The capital of Pennsylvania is"}, model, tokenizer, 1, 9999, 5)


    app = Bottle()


    @app.hook('after_request')
    def enable_cors():
        """
        You need to add some headers to each request.
        Don't use the wildcard '*' for Access-Control-Allow-Origin in production.
        """
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'


    @app.route("/get_config", method=['GET'])
    def get_config():
        return  {
            "tokenizer_name_or_path": tokenizer.name_or_path,
            "max_input_len": max_input_len,
            "max_decode_len": max_decode_len
        }


    @app.route('/predict', method=['POST'])
    def predict():
        dp = request.json
        # pdb.set_trace()
        task = dp["task"]


        if task in ["evidence_extraction_with_fixfactuality"]:
            dscreate_func = TASK_TO_DSCREATE[task]
            newdp = dscreate_func(dp)
            predict_generation(newdp, model=model, tokenizer=tokenizer, nbeams=4, max_input_len=max_input_len, max_decode_len=max_decode_len)
        else:
            raise NotImplementedError

        # at this point the newdp should be updated in place with results
        if "prediction" not in newdp:
            return {"result": None, "success": False}


        if task == "evidence_extraction_with_fixfactuality":
            return {"result": newdp, "success": True}
        else:
            raise NotImplementedError


    run(app, host="localhost", port=args.port, debug=True)
