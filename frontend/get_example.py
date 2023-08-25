import glob
import json

class ArticleGetter():
    def __init__(self):
        self.refresh()

    def refresh(self):
        all_files = glob.glob("../datasets/examples/saved/*.json")
        self.full = [json.load(open(x)) for x in all_files]
        self.full = sorted(self.full, key=lambda i:i["id"])
        self.full = [{"input_lines":[], "output_lines":[], "id":"New (empty doc)"}] + self.full
        print(all_files)

    def get_all_ids(self):
        self.refresh()
        all_ids = [x["id"] for x in self.full]
        return all_ids

    def get_article(self, article_index):
        example: dict = self.full[article_index]
        input_lines = example["input_lines"]
        output_lines = example["output_lines"]

        return_obj = {
            "input_lines": input_lines,
            "id": example["id"],
            "output_lines": output_lines,
        }

        if "question" in example:
            return_obj["question"] = example["question"]

        return return_obj

